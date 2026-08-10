"""Availability and monitor-state domain models."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from pydantic import BaseModel, Field


class AvailabilitySnapshot(BaseModel):
    checked_at: datetime
    source_url: str
    service_active: bool
    available_dates: list[date] = Field(default_factory=list)
    candidate_dates: list[date] = Field(default_factory=list)
    booked_dates: list[date] = Field(default_factory=list)
    blocked_dates: list[date] = Field(default_factory=list)
    page_fingerprint: str

    @property
    def availability_key(self) -> str:
        if not self.available_dates:
            return ""
        payload = "|".join(item.isoformat() for item in sorted(self.available_dates))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AlertClaim(BaseModel):
    availability_key: str
    available_dates: list[date]
    claimed_at: datetime


class FailureRecord(BaseModel):
    consecutive_failures: int
    should_alert: bool = False


class CheckResult(BaseModel):
    outcome: str
    checked_at: datetime
    available_dates: list[date] = Field(default_factory=list)
    notification_sent: bool = False
    detail: str | None = None


class MonitorStatus(BaseModel):
    running: bool
    last_check_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    available_dates: list[date] = Field(default_factory=list)
    last_notification_at: datetime | None = None

