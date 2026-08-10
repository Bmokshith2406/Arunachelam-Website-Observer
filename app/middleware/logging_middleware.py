"""Request correlation and latency logging."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders


logger = logging.getLogger(__name__)
EXEMPT_PATHS = {"/metrics", "/healthz/live", "/healthz/ready", "/openapi.json"}


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        headers = Headers(scope=scope)
        trace_id = headers.get("x-cloud-trace-context") or str(uuid.uuid4())
        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Trace-ID"] = trace_id
            await send(message)

        if path in EXEMPT_PATHS:
            await self.app(scope, receive, send_wrapper)
            return

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "HTTP request failed",
                extra={"method": method, "path": path, "trace_id": trace_id},
            )
            raise
        logger.info(
            "HTTP request completed",
            extra={
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "trace_id": trace_id,
            },
        )

