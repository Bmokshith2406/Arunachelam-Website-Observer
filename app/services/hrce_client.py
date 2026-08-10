"""Resilient, read-only client for the official HR&CE service page."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

import httpx

from app.core.config import Settings


logger = logging.getLogger(__name__)


class AvailabilityFetchError(RuntimeError):
    """All configured HR&CE endpoints or retries failed."""


@dataclass(frozen=True)
class PageResponse:
    html: str
    source_url: str
    status_code: int


class HRCEClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=settings.HRCE_CONNECT_TIMEOUT_SECONDS,
            read=settings.HRCE_REQUEST_TIMEOUT_SECONDS,
            write=settings.HRCE_REQUEST_TIMEOUT_SECONDS,
            pool=settings.HRCE_CONNECT_TIMEOUT_SECONDS,
        )
        self.client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            headers={
                "User-Agent": settings.HRCE_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-IN,en;q=0.8,ta;q=0.6",
                "Cache-Control": "no-cache",
            },
        )

    async def fetch_booking_page(self) -> PageResponse:
        errors: list[str] = []
        urls = list(dict.fromkeys([self.settings.HRCE_PRIMARY_URL, self.settings.HRCE_FALLBACK_URL]))

        for url in urls:
            for attempt in range(1, self.settings.HRCE_MAX_ATTEMPTS_PER_URL + 1):
                try:
                    response = await self.client.get(url)
                    response.raise_for_status()
                    if len(response.content) < self.settings.HRCE_MIN_RESPONSE_BYTES:
                        raise AvailabilityFetchError(
                            f"response was unexpectedly small ({len(response.content)} bytes)"
                        )
                    return PageResponse(
                        html=response.text,
                        source_url=str(response.url),
                        status_code=response.status_code,
                    )
                except asyncio.CancelledError:
                    raise
                except (httpx.HTTPError, AvailabilityFetchError) as exc:
                    detail = f"{url} attempt {attempt}: {type(exc).__name__}: {exc}"
                    errors.append(detail)
                    logger.warning("HRCE request attempt failed", extra={"detail": detail})
                    if attempt < self.settings.HRCE_MAX_ATTEMPTS_PER_URL:
                        delay = self.settings.HRCE_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                        await asyncio.sleep(delay + random.uniform(0, delay * 0.2))

        raise AvailabilityFetchError("; ".join(errors))

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

