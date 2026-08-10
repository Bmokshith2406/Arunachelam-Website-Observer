"""Prometheus HTTP metrics setup."""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator


def setup_telemetry(app: FastAPI) -> None:
    Instrumentator(excluded_handlers=["/metrics", "/healthz/.*"]).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )

