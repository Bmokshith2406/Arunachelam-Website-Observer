"""FastAPI entrypoint for Cloud Run."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.telemetry import setup_telemetry
from app.db.firestore import FirestoreStateStore
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routes.monitoring import router as monitoring_router
from app.services.availability_parser import AvailabilityParser
from app.services.hrce_client import HRCEClient
from app.services.monitor_service import MonitorService
from app.services.notification_service import NotificationService


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_runtime_safety()
    monitor: MonitorService | None = None
    if settings.MONITOR_ENABLED:
        monitor = MonitorService(
            settings=settings,
            client=HRCEClient(settings),
            parser=AvailabilityParser(),
            state_store=FirestoreStateStore(settings),
            notifications=NotificationService(settings),
        )
        app.state.monitor = monitor
        await monitor.start()
    else:
        logger.warning("Ticket monitor is disabled")
        app.state.monitor = None

    yield

    if monitor:
        await monitor.stop()


app = FastAPI(
    title="Arunachalam Ticket Observability Nanoservice",
    description=(
        "Monitors the official HR&CE ₹2,500 Swami Amman Special Abhishekam "
        "calendar and sends deduplicated Gmail alerts."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

setup_telemetry(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(monitoring_router)


@app.get("/", include_in_schema=False)
async def redirect_to_docs():
    return RedirectResponse(url="/docs")


@app.get("/healthz/live", tags=["Diagnostics"])
async def liveness_check():
    return {"status": "alive"}


@app.get("/healthz/ready", tags=["Diagnostics"])
async def readiness_check(response: Response):
    monitor = getattr(app.state, "monitor", None)
    if settings.MONITOR_ENABLED and (monitor is None or not monitor.task_is_healthy()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "reason": "monitor task is not running"}
    monitor_status = await monitor.get_status() if monitor else None
    return {
        "status": "ready",
        "monitor": monitor_status.model_dump(mode="json") if monitor_status else "disabled",
    }

