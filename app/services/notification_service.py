"""Gmail SMTP notifications with a configurable rapid alert burst."""

from __future__ import annotations

import asyncio
import html
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Any

import aiosmtplib

from app.core.config import Settings


logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        settings: Settings,
        smtp_factory: Callable[..., Any] = aiosmtplib.SMTP,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.settings = settings
        self.smtp_factory = smtp_factory
        self.sleep = sleep

    async def send_availability_burst(
        self, available_dates: list[date], booking_url: str
    ) -> int:
        if not self.settings.SMTP_USERNAME or not self.settings.SMTP_APP_PASSWORD:
            raise RuntimeError("Gmail SMTP credentials are not configured")
        if not self.settings.ALERT_RECIPIENTS:
            raise RuntimeError("ALERT_RECIPIENTS is empty")

        burst_id = uuid.uuid4().hex
        smtp = self._new_smtp_client()
        sent = 0
        await smtp.connect()
        try:
            await smtp.login(
                str(self.settings.SMTP_USERNAME), self.settings.SMTP_APP_PASSWORD
            )
            for index in range(1, self.settings.EMAIL_BURST_COUNT + 1):
                message = self._availability_message(
                    available_dates=available_dates,
                    booking_url=booking_url,
                    burst_id=burst_id,
                    index=index,
                )
                await smtp.send_message(message)
                sent += 1
                if index < self.settings.EMAIL_BURST_COUNT:
                    await self.sleep(self.settings.EMAIL_BURST_GAP_SECONDS)
        finally:
            try:
                await smtp.quit()
            except Exception:
                logger.warning("SMTP connection did not close cleanly", exc_info=True)
        return sent

    async def send_operational_alert(self, error: str, failure_count: int) -> None:
        if not self.settings.SMTP_USERNAME or not self.settings.SMTP_APP_PASSWORD:
            logger.error("Cannot send operational alert because SMTP is not configured")
            return
        smtp = self._new_smtp_client()
        await smtp.connect()
        try:
            await smtp.login(
                str(self.settings.SMTP_USERNAME), self.settings.SMTP_APP_PASSWORD
            )
            message = self._base_message()
            message["Subject"] = (
                f"[Monitor warning] HR&CE check failed {failure_count} times"
            )
            message.set_content(
                "The ticket monitor is still running, but repeated HR&CE checks failed.\n\n"
                f"Latest error: {error}\n\n"
                "The service will keep retrying automatically."
            )
            await smtp.send_message(message)
        finally:
            try:
                await smtp.quit()
            except Exception:
                logger.warning("SMTP connection did not close cleanly", exc_info=True)

    def _new_smtp_client(self):
        use_tls = self.settings.SMTP_PORT == 465
        return self.smtp_factory(
            hostname=self.settings.SMTP_HOST,
            port=self.settings.SMTP_PORT,
            timeout=self.settings.SMTP_TIMEOUT_SECONDS,
            use_tls=use_tls,
            start_tls=self.settings.SMTP_STARTTLS if not use_tls else False,
        )

    def _base_message(self) -> EmailMessage:
        message = EmailMessage()
        message["From"] = (
            f"{self.settings.SMTP_FROM_NAME} <{self.settings.effective_from_email()}>"
        )
        message["To"] = ", ".join(str(item) for item in self.settings.ALERT_RECIPIENTS)
        message["Date"] = format_datetime(datetime.now(timezone.utc))
        message["Message-ID"] = make_msgid()
        return message

    def _availability_message(
        self,
        available_dates: list[date],
        booking_url: str,
        burst_id: str,
        index: int,
    ) -> EmailMessage:
        formatted_dates = [item.strftime("%A, %d %B %Y") for item in available_dates]
        date_lines = "\n".join(f"- {item}" for item in formatted_dates)
        escaped_dates = "".join(f"<li>{html.escape(item)}</li>" for item in formatted_dates)
        message = self._base_message()
        message["Subject"] = (
            f"[TICKETS OPEN {index}/{self.settings.EMAIL_BURST_COUNT}] "
            "₹2,500 Arunachalam Abhishekam"
        )
        message["X-Alert-Burst-ID"] = burst_id
        message.set_content(
            "₹2,500 Swami Amman Special Abhishekam tickets appear to be available.\n\n"
            f"Available dates:\n{date_lines}\n\nBook immediately:\n{booking_url}\n\n"
            "Availability can change at any moment. A ticket is not reserved until the "
            "official booking and payment complete."
        )
        message.add_alternative(
            "<html><body>"
            "<h2>₹2,500 Arunachalam tickets appear to be open</h2>"
            f"<ul>{escaped_dates}</ul>"
            f'<p><a href="{html.escape(booking_url, quote=True)}"><strong>Book now</strong></a></p>'
            "<p>Availability can change at any moment. A ticket is not reserved until "
            "the official booking and payment complete.</p>"
            "</body></html>",
            subtype="html",
        )
        return message

