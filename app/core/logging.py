"""Structured JSON logging compatible with Google Cloud Logging."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


STANDARD_LOG_RECORD_KEYS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "filename": record.filename,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_RECORD_KEYS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google.api_core").setLevel(logging.WARNING)

