from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.firestore import MemoryStateStore
from app.services.availability_parser import AvailabilityParser
from app.services.hrce_client import AvailabilityFetchError, PageResponse
from app.services.monitor_service import MonitorService


FIXTURE = Path(__file__).parent / "fixtures" / "available_page.html"


class SequenceClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.closed = False

    async def fetch_booking_page(self):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return PageResponse(html=outcome, source_url="https://example.test", status_code=200)

    async def close(self):
        self.closed = True


class FakeNotifications:
    def __init__(self):
        self.bursts = []
        self.operational_alerts = []

    async def send_availability_burst(self, dates, booking_url):
        self.bursts.append((list(dates), booking_url))
        return 10

    async def send_operational_alert(self, error, failure_count):
        self.operational_alerts.append((error, failure_count))


def make_settings(**overrides):
    return Settings(
        MONITOR_ENABLED=False,
        FAILURE_ALERT_THRESHOLD=3,
        ALERT_RECIPIENTS=["recipient@gmail.com"],
        SMTP_USERNAME="sender@gmail.com",
        SMTP_APP_PASSWORD="app-password",
        **overrides,
    )


@pytest.mark.asyncio
async def test_same_open_state_generates_only_one_burst():
    html = FIXTURE.read_text(encoding="utf-8")
    notifications = FakeNotifications()
    monitor = MonitorService(
        settings=make_settings(),
        client=SequenceClient([html, html]),
        parser=AvailabilityParser(),
        state_store=MemoryStateStore(),
        notifications=notifications,
    )

    first = await monitor.check_once()
    second = await monitor.check_once()

    assert first.outcome == "alert_sent"
    assert second.outcome == "available"
    assert len(notifications.bursts) == 1


@pytest.mark.asyncio
async def test_closed_state_resets_deduplication_for_a_reopening():
    html = FIXTURE.read_text(encoding="utf-8")
    closed = html.replace(
        'var booked_date_array=["11-8-2026"];',
        'var booked_date_array=["11-8-2026","13-8-2026","14-8-2026"];',
    ).replace(
        'var blocked_date_array=["12-8-2026"];',
        'var blocked_date_array=["12-8-2026"];',
    )
    notifications = FakeNotifications()
    monitor = MonitorService(
        settings=make_settings(),
        client=SequenceClient([html, closed, html]),
        parser=AvailabilityParser(),
        state_store=MemoryStateStore(),
        notifications=notifications,
    )

    assert (await monitor.check_once()).outcome == "alert_sent"
    assert (await monitor.check_once()).outcome == "unavailable"
    assert (await monitor.check_once()).outcome == "alert_sent"
    assert len(notifications.bursts) == 2


@pytest.mark.asyncio
async def test_transient_hrce_failure_does_not_break_next_check_or_clear_state():
    html = FIXTURE.read_text(encoding="utf-8")
    state = MemoryStateStore()
    notifications = FakeNotifications()
    monitor = MonitorService(
        settings=make_settings(),
        client=SequenceClient([AvailabilityFetchError("timeout"), html]),
        parser=AvailabilityParser(),
        state_store=state,
        notifications=notifications,
    )

    failed = await monitor.check_once()
    recovered = await monitor.check_once()

    assert failed.outcome == "failed"
    assert recovered.outcome == "alert_sent"
    assert len(notifications.bursts) == 1
    assert (await state.get_status())["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_repeated_failures_send_only_one_health_warning():
    notifications = FakeNotifications()
    monitor = MonitorService(
        settings=make_settings(),
        client=SequenceClient(
            [
                AvailabilityFetchError("one"),
                AvailabilityFetchError("two"),
                AvailabilityFetchError("three"),
                AvailabilityFetchError("four"),
            ]
        ),
        parser=AvailabilityParser(),
        state_store=MemoryStateStore(),
        notifications=notifications,
    )

    for _ in range(4):
        assert (await monitor.check_once()).outcome == "failed"

    assert len(notifications.operational_alerts) == 1
    assert notifications.operational_alerts[0][1] == 3

