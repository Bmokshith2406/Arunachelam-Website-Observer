"""Parse the public HR&CE booking calendar without executing a booking."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone

from app.models.availability import AvailabilitySnapshot


class AvailabilityParsingError(RuntimeError):
    """Raised when a response no longer resembles the expected booking page."""


class AvailabilityParser:
    SERVICE_MARKERS = (
        "63716",
        "சுவாமி அம்மன் சிறப்பு அபிஷேகம்",
        "Swami Amman Special Abhishekam",
    )
    INACTIVE_MARKERS = (
        "இந்த ஆன்லைன் சேவையை தற்பொழுது கோயில் செயல்படுத்தவில்லை",
        "Service not available for at this moment",
    )
    ARRAY_NAMES = {
        "candidates": "disableDates",
        "booked": "booked_date_array",
        "blocked": "blocked_date_array",
        "festival": "festival_date_array",
        "special": "special_date_array",
    }
    DATE_PATTERN = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")

    def parse(self, html: str, source_url: str) -> AvailabilitySnapshot:
        now = datetime.now(timezone.utc)
        fingerprint = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()

        if any(marker in html for marker in self.INACTIVE_MARKERS):
            return AvailabilitySnapshot(
                checked_at=now,
                source_url=source_url,
                service_active=False,
                page_fingerprint=fingerprint,
            )

        if not any(marker in html for marker in self.SERVICE_MARKERS):
            raise AvailabilityParsingError("The expected ₹2,500 service marker is missing")

        arrays = {
            key: self._extract_date_array(html, javascript_name)
            for key, javascript_name in self.ARRAY_NAMES.items()
        }
        if not any(javascript_name in html for javascript_name in self.ARRAY_NAMES.values()):
            raise AvailabilityParsingError("Booking calendar arrays are missing")

        candidate_dates = arrays["candidates"] | arrays["festival"] | arrays["special"]
        unavailable_dates = arrays["booked"] | arrays["blocked"]
        available_dates = candidate_dates - unavailable_dates

        return AvailabilitySnapshot(
            checked_at=now,
            source_url=source_url,
            service_active=True,
            available_dates=sorted(available_dates),
            candidate_dates=sorted(candidate_dates),
            booked_dates=sorted(arrays["booked"]),
            blocked_dates=sorted(arrays["blocked"]),
            page_fingerprint=fingerprint,
        )

    def _extract_date_array(self, html: str, variable_name: str) -> set[date]:
        match = re.search(
            rf"\b{re.escape(variable_name)}\s*=\s*\[(.*?)\]\s*;",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return set()

        parsed: set[date] = set()
        for day, month, year in self.DATE_PATTERN.findall(match.group(1)):
            try:
                parsed.add(date(int(year), int(month), int(day)))
            except ValueError as exc:
                raise AvailabilityParsingError(
                    f"Invalid date in {variable_name}: {day}-{month}-{year}"
                ) from exc
        return parsed

