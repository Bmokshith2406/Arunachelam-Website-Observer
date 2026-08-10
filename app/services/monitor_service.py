"""Long-running availability monitor with failure isolation and deduplication."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from prometheus_client import Counter, Gauge, Histogram

from app.core.config import Settings
from app.db.firestore import StateStore
from app.models.availability import CheckResult, MonitorStatus
from app.services.availability_parser import AvailabilityParser
from app.services.hrce_client import HRCEClient
from app.services.notification_service import NotificationService


logger = logging.getLogger(__name__)

CHECKS_TOTAL = Counter(
    "ticket_monitor_checks_total", "Availability checks", labelnames=("outcome",)
)
CHECK_DURATION = Histogram(
    "ticket_monitor_check_duration_seconds", "Availability check duration"
)
AVAILABLE_DATES = Gauge(
    "ticket_monitor_available_dates", "Number of currently available dates"
)
CONSECUTIVE_FAILURES = Gauge(
    "ticket_monitor_consecutive_failures", "Consecutive failed availability checks"
)
EMAILS_SENT_TOTAL = Counter(
    "ticket_monitor_emails_sent_total", "Successfully submitted availability emails"
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        client: HRCEClient,
        parser: AvailabilityParser,
        state_store: StateStore,
        notifications: NotificationService,
    ):
        self.settings = settings
        self.client = client
        self.parser = parser
        self.state_store = state_store
        self.notifications = notifications
        self.owner_id = uuid.uuid4().hex
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._check_lock = asyncio.Lock()
        self._status = MonitorStatus(running=False)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._status.running = True
        self._task = asyncio.create_task(self._run_loop(), name="hrce-ticket-monitor")
        logger.info(
            "Ticket monitor started",
            extra={"poll_interval_seconds": self.settings.POLL_INTERVAL_SECONDS},
        )

    async def stop(self) -> None:
        self._status.running = False
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.close()
        logger.info("Ticket monitor stopped")

    def task_is_healthy(self) -> bool:
        return bool(self._task and not self._task.done())

    async def get_status(self) -> MonitorStatus:
        return self._status.model_copy(deep=True)

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            cycle_started = time.monotonic()
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # This is the final containment boundary. Individual integrations
                # are handled in check_once, but no unexpected exception may kill
                # the all-day monitoring task.
                logger.exception("Unexpected monitor-loop error; monitoring will continue")
                CHECKS_TOTAL.labels(outcome="loop_error").inc()

            elapsed = time.monotonic() - cycle_started
            remaining = max(0.0, self.settings.POLL_INTERVAL_SECONDS - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=remaining)
            except TimeoutError:
                pass

    async def check_once(self) -> CheckResult:
        async with self._check_lock:
            started_at = utc_now()
            started_monotonic = time.monotonic()
            self._status.last_check_started_at = started_at
            acquired = False

            try:
                acquired = await self.state_store.acquire_lease(
                    self.owner_id, self.settings.MONITOR_LEASE_SECONDS
                )
                if not acquired:
                    CHECKS_TOTAL.labels(outcome="lease_skipped").inc()
                    return CheckResult(
                        outcome="lease_skipped",
                        checked_at=started_at,
                        detail="Another instance currently owns the monitor lease",
                    )

                page = await self.client.fetch_booking_page()
                snapshot = self.parser.parse(page.html, page.source_url)
                claim = await self.state_store.record_success_and_claim_alert(snapshot)

                self._status.last_success_at = utc_now()
                self._status.last_error = None
                self._status.consecutive_failures = 0
                self._status.available_dates = snapshot.available_dates
                AVAILABLE_DATES.set(len(snapshot.available_dates))
                CONSECUTIVE_FAILURES.set(0)

                notification_sent = False
                outcome = "available" if snapshot.available_dates else "unavailable"
                detail = None
                if claim:
                    try:
                        sent = await self.notifications.send_availability_burst(
                            claim.available_dates, self.settings.BOOKING_LINK_URL
                        )
                        await self.state_store.complete_alert(
                            claim.availability_key, success=True
                        )
                        self._status.last_notification_at = utc_now()
                        EMAILS_SENT_TOTAL.inc(sent)
                        notification_sent = True
                        outcome = "alert_sent"
                        detail = f"Submitted {sent} alert emails"
                    except asyncio.CancelledError:
                        await self._best_effort_complete_alert(
                            claim.availability_key, success=False
                        )
                        raise
                    except Exception as exc:
                        await self._best_effort_complete_alert(
                            claim.availability_key, success=False
                        )
                        self._status.last_error = (
                            f"Notification failure: {type(exc).__name__}: {exc}"
                        )
                        outcome = "notification_failed"
                        detail = self._status.last_error
                        logger.exception(
                            "Availability found but email burst failed; it will be retried"
                        )

                CHECKS_TOTAL.labels(outcome=outcome).inc()
                logger.info(
                    "Availability check completed",
                    extra={
                        "outcome": outcome,
                        "available_dates": [
                            item.isoformat() for item in snapshot.available_dates
                        ],
                        "source_url": snapshot.source_url,
                    },
                )
                return CheckResult(
                    outcome=outcome,
                    checked_at=started_at,
                    available_dates=snapshot.available_dates,
                    notification_sent=notification_sent,
                    detail=detail,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._status.last_error = error
                self._status.consecutive_failures += 1
                CONSECUTIVE_FAILURES.set(self._status.consecutive_failures)
                CHECKS_TOTAL.labels(outcome="failed").inc()
                logger.exception(
                    "Availability check failed; last successful state is preserved"
                )

                try:
                    failure = await self.state_store.record_failure(
                        error, self.settings.FAILURE_ALERT_THRESHOLD
                    )
                    self._status.consecutive_failures = failure.consecutive_failures
                    CONSECUTIVE_FAILURES.set(failure.consecutive_failures)
                    if failure.should_alert:
                        try:
                            await self.notifications.send_operational_alert(
                                error, failure.consecutive_failures
                            )
                        except Exception:
                            logger.exception("Failed to send monitor-health warning email")
                except Exception:
                    logger.exception(
                        "Could not persist failure state; local monitor loop will continue"
                    )

                return CheckResult(
                    outcome="failed", checked_at=started_at, detail=error
                )
            finally:
                CHECK_DURATION.observe(time.monotonic() - started_monotonic)
                if acquired:
                    try:
                        await self.state_store.release_lease(self.owner_id)
                    except Exception:
                        logger.exception("Failed to release Firestore monitor lease")

    async def _best_effort_complete_alert(
        self, availability_key: str, success: bool
    ) -> None:
        try:
            await self.state_store.complete_alert(availability_key, success)
        except Exception:
            logger.exception("Could not update the Firestore alert claim")

