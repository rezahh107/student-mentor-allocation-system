from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Dict

MASKED_FIELDS = {"email", "phone", "national_id"}
CORRELATION_ID = ContextVar("correlation_id", default="unknown")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - exercised via tests
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "correlation_id": CORRELATION_ID.get(),
        }
        for key, value in getattr(record, "extra", {}).items():
            payload[key] = _mask_if_needed(key, value)
        return json.dumps(payload, ensure_ascii=False)


def _mask_if_needed(key: str, value: Any) -> Any:
    if key in MASKED_FIELDS and isinstance(value, str):
        return f"***{hash(value) & 0xffff:x}"
    return value


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    app_logger = logging.getLogger("automation_audit")
    app_logger.setLevel(level)
    app_logger.propagate = True


def set_correlation_id(value: str) -> None:
    CORRELATION_ID.set(value)


def log_json(message: str, **extra: Any) -> None:
    logger = logging.getLogger("automation_audit")
    logger.info(message, extra={"extra": extra})
