from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.availability import CheckResult, MonitorStatus
from app.routes.monitoring import router


class DummyMonitor:
    async def get_status(self):
        return MonitorStatus(running=True)

    async def check_once(self):
        return CheckResult(outcome="unavailable", checked_at=datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_management_routes_require_api_key():
    app = FastAPI()
    app.state.monitor = DummyMonitor()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/api/v1/monitor/status")
        allowed = await client.get(
            "/api/v1/monitor/status", headers={"X-API-Key": "change-me-in-production"}
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["running"] is True

