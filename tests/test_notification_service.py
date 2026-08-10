from datetime import date

import pytest

from app.core.config import Settings
from app.services.notification_service import NotificationService


class FakeSMTP:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = []
        self.connected = False
        self.login_args = None
        self.closed = False

    async def connect(self):
        self.connected = True

    async def login(self, username, password):
        self.login_args = (username, password)

    async def send_message(self, message):
        self.messages.append(message)

    async def quit(self):
        self.closed = True


@pytest.mark.asyncio
async def test_sends_ten_messages_with_half_second_gaps():
    smtp = FakeSMTP()
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    settings = Settings(
        SMTP_USERNAME="sender@gmail.com",
        SMTP_APP_PASSWORD="app-password",
        SMTP_FROM_EMAIL="sender@gmail.com",
        ALERT_RECIPIENTS=["recipient@gmail.com"],
        EMAIL_BURST_COUNT=10,
        EMAIL_BURST_GAP_SECONDS=0.5,
    )
    service = NotificationService(
        settings,
        smtp_factory=lambda **kwargs: smtp,
        sleep=fake_sleep,
    )

    sent = await service.send_availability_burst(
        [date(2026, 8, 13)], "https://example.test/book"
    )

    assert sent == 10
    assert len(smtp.messages) == 10
    assert sleeps == [0.5] * 9
    assert smtp.connected is True
    assert smtp.closed is True
    assert smtp.login_args == ("sender@gmail.com", "app-password")
    assert all("TICKETS OPEN" in message["Subject"] for message in smtp.messages)

