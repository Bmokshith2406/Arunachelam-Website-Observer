"""Protected monitor-management API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.config import settings
from app.models.availability import CheckResult, MonitorStatus


router = APIRouter(prefix="/api/v1/monitor", tags=["Monitoring"])


def require_admin_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if not settings.admin_key_matches(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )


def get_monitor(request: Request):
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitor is disabled or not initialized",
        )
    return monitor


@router.get("/status", response_model=MonitorStatus)
async def monitor_status(
    request: Request,
    _: Annotated[None, Depends(require_admin_api_key)],
) -> MonitorStatus:
    return await get_monitor(request).get_status()


@router.post("/check", response_model=CheckResult)
async def trigger_check(
    request: Request,
    _: Annotated[None, Depends(require_admin_api_key)],
) -> CheckResult:
    return await get_monitor(request).check_once()
