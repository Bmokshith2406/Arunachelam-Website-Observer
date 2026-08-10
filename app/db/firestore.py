"""Firestore-backed state, locking, and alert deduplication."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from google.cloud import firestore

from app.core.config import Settings
from app.models.availability import AlertClaim, AvailabilitySnapshot, FailureRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class StateStore(Protocol):
    async def acquire_lease(self, owner: str, ttl_seconds: int) -> bool: ...
    async def release_lease(self, owner: str) -> None: ...
    async def record_success_and_claim_alert(
        self, snapshot: AvailabilitySnapshot
    ) -> AlertClaim | None: ...
    async def complete_alert(self, availability_key: str, success: bool) -> None: ...
    async def record_failure(self, error: str, alert_threshold: int) -> FailureRecord: ...
    async def get_status(self) -> dict[str, Any]: ...


class FirestoreStateStore:
    """Use one Firestore document as a transactionally updated state machine."""

    def __init__(self, settings: Settings):
        kwargs: dict[str, str] = {"database": settings.FIRESTORE_DATABASE}
        if settings.FIRESTORE_PROJECT_ID:
            kwargs["project"] = settings.FIRESTORE_PROJECT_ID
        self.client = firestore.AsyncClient(**kwargs)
        self.document = self.client.collection(settings.FIRESTORE_COLLECTION).document(
            settings.FIRESTORE_STATE_DOCUMENT
        )
        self.alert_claim_ttl_seconds = settings.ALERT_CLAIM_TTL_SECONDS

    async def acquire_lease(self, owner: str, ttl_seconds: int) -> bool:
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def acquire(transaction):
            snapshot = await self.document.get(transaction=transaction)
            data = snapshot.to_dict() or {}
            now = utc_now()
            current_owner = data.get("lease_owner")
            lease_until = _aware(data.get("lease_until"))
            if current_owner != owner and lease_until and lease_until > now:
                return False
            transaction.set(
                self.document,
                {
                    "lease_owner": owner,
                    "lease_until": now + timedelta(seconds=ttl_seconds),
                    "updated_at": now,
                },
                merge=True,
            )
            return True

        return bool(await acquire(transaction))

    async def release_lease(self, owner: str) -> None:
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def release(transaction):
            snapshot = await self.document.get(transaction=transaction)
            data = snapshot.to_dict() or {}
            if data.get("lease_owner") == owner:
                transaction.set(
                    self.document,
                    {"lease_owner": None, "lease_until": None, "updated_at": utc_now()},
                    merge=True,
                )

        await release(transaction)

    async def record_success_and_claim_alert(
        self, snapshot: AvailabilitySnapshot
    ) -> AlertClaim | None:
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def update(transaction):
            stored = await self.document.get(transaction=transaction)
            data = stored.to_dict() or {}
            now = utc_now()
            key = snapshot.availability_key
            available = [item.isoformat() for item in snapshot.available_dates]
            update_data: dict[str, Any] = {
                "last_check_started_at": snapshot.checked_at,
                "last_success_at": now,
                "last_error": None,
                "consecutive_failures": 0,
                "failure_alert_sent": False,
                "service_active": snapshot.service_active,
                "available_dates": available,
                "candidate_dates": [item.isoformat() for item in snapshot.candidate_dates],
                "booked_dates": [item.isoformat() for item in snapshot.booked_dates],
                "blocked_dates": [item.isoformat() for item in snapshot.blocked_dates],
                "availability_key": key,
                "source_url": snapshot.source_url,
                "page_fingerprint": snapshot.page_fingerprint,
                "updated_at": now,
            }

            if not key:
                update_data.update(
                    {
                        "last_alerted_key": "",
                        "pending_alert_key": None,
                        "pending_alert_until": None,
                    }
                )
                transaction.set(self.document, update_data, merge=True)
                return None

            last_alerted_key = data.get("last_alerted_key", "")
            pending_key = data.get("pending_alert_key")
            pending_until = _aware(data.get("pending_alert_until"))
            already_claimed = pending_key == key and pending_until and pending_until > now
            if last_alerted_key == key or already_claimed:
                transaction.set(self.document, update_data, merge=True)
                return None

            update_data.update(
                {
                    "pending_alert_key": key,
                    "pending_alert_until": now
                    + timedelta(seconds=self.alert_claim_ttl_seconds),
                }
            )
            transaction.set(self.document, update_data, merge=True)
            return AlertClaim(
                availability_key=key,
                available_dates=snapshot.available_dates,
                claimed_at=now,
            )

        return await update(transaction)

    async def complete_alert(self, availability_key: str, success: bool) -> None:
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def complete(transaction):
            stored = await self.document.get(transaction=transaction)
            data = stored.to_dict() or {}
            if data.get("pending_alert_key") != availability_key:
                return
            update_data: dict[str, Any] = {
                "pending_alert_key": None,
                "pending_alert_until": None,
                "updated_at": utc_now(),
            }
            if success:
                update_data["last_alerted_key"] = availability_key
                update_data["last_notification_at"] = utc_now()
            transaction.set(self.document, update_data, merge=True)

        await complete(transaction)

    async def record_failure(self, error: str, alert_threshold: int) -> FailureRecord:
        transaction = self.client.transaction()

        @firestore.async_transactional
        async def update(transaction):
            stored = await self.document.get(transaction=transaction)
            data = stored.to_dict() or {}
            count = int(data.get("consecutive_failures", 0)) + 1
            failure_alert_sent = bool(data.get("failure_alert_sent", False))
            should_alert = count >= alert_threshold and not failure_alert_sent
            transaction.set(
                self.document,
                {
                    "last_check_started_at": utc_now(),
                    "last_error": error[:2_000],
                    "consecutive_failures": count,
                    "failure_alert_sent": failure_alert_sent or should_alert,
                    "updated_at": utc_now(),
                },
                merge=True,
            )
            return FailureRecord(
                consecutive_failures=count,
                should_alert=should_alert,
            )

        return await update(transaction)

    async def get_status(self) -> dict[str, Any]:
        snapshot = await self.document.get()
        return snapshot.to_dict() or {}


class MemoryStateStore:
    """Deterministic in-memory adapter used by unit tests and local development."""

    def __init__(self, alert_claim_ttl_seconds: int = 120):
        self.data: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.alert_claim_ttl_seconds = alert_claim_ttl_seconds

    async def acquire_lease(self, owner: str, ttl_seconds: int) -> bool:
        async with self._lock:
            now = utc_now()
            current_owner = self.data.get("lease_owner")
            lease_until = _aware(self.data.get("lease_until"))
            if current_owner != owner and lease_until and lease_until > now:
                return False
            self.data.update(
                {"lease_owner": owner, "lease_until": now + timedelta(seconds=ttl_seconds)}
            )
            return True

    async def release_lease(self, owner: str) -> None:
        async with self._lock:
            if self.data.get("lease_owner") == owner:
                self.data.update({"lease_owner": None, "lease_until": None})

    async def record_success_and_claim_alert(
        self, snapshot: AvailabilitySnapshot
    ) -> AlertClaim | None:
        async with self._lock:
            now = utc_now()
            key = snapshot.availability_key
            self.data.update(
                {
                    "last_success_at": now,
                    "last_error": None,
                    "consecutive_failures": 0,
                    "failure_alert_sent": False,
                    "service_active": snapshot.service_active,
                    "available_dates": [item.isoformat() for item in snapshot.available_dates],
                    "availability_key": key,
                    "source_url": snapshot.source_url,
                }
            )
            if not key:
                self.data.update(
                    {"last_alerted_key": "", "pending_alert_key": None, "pending_alert_until": None}
                )
                return None
            pending_until = _aware(self.data.get("pending_alert_until"))
            if self.data.get("last_alerted_key") == key:
                return None
            if self.data.get("pending_alert_key") == key and pending_until and pending_until > now:
                return None
            self.data.update(
                {
                    "pending_alert_key": key,
                    "pending_alert_until": now
                    + timedelta(seconds=self.alert_claim_ttl_seconds),
                }
            )
            return AlertClaim(
                availability_key=key,
                available_dates=snapshot.available_dates,
                claimed_at=now,
            )

    async def complete_alert(self, availability_key: str, success: bool) -> None:
        async with self._lock:
            if self.data.get("pending_alert_key") != availability_key:
                return
            self.data.update({"pending_alert_key": None, "pending_alert_until": None})
            if success:
                self.data.update(
                    {"last_alerted_key": availability_key, "last_notification_at": utc_now()}
                )

    async def record_failure(self, error: str, alert_threshold: int) -> FailureRecord:
        async with self._lock:
            count = int(self.data.get("consecutive_failures", 0)) + 1
            should_alert = count >= alert_threshold and not self.data.get(
                "failure_alert_sent", False
            )
            self.data.update(
                {
                    "last_error": error,
                    "consecutive_failures": count,
                    "failure_alert_sent": self.data.get("failure_alert_sent", False)
                    or should_alert,
                }
            )
            return FailureRecord(consecutive_failures=count, should_alert=should_alert)

    async def get_status(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self.data)

