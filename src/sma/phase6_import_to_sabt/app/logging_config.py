from __future__ import annotations

import logging
import sys
from typing import Any, Dict

import orjson


SENSITIVE_KEYS = {
    "authorization",
    "token",
    "secret",
    "mobile",
    "national_id",
    "mentor_id",
}


def _mask_value(value: str) -> str:
    if not value:
        return value
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def configure_logging(service_name: str, enable_debug: bool) -> None:
    level = logging.DEBUG if enable_debug else logging.INFO
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONLogFormatter(service_name=service_name))

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


class JSONLogFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        correlation_id = getattr(record, "correlation_id", None)
        payload: Dict[str, Any] = {
            "service": self.service_name,
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": correlation_id,
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            lowered = key.lower()
            if key in payload or key.startswith("_"):
                continue
            if lowered in {
                "msg",
                "args",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcname",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "created",
                "msecs",
                "relativecreated",
                "thread",
                "threadname",
                "processname",
                "process",
                "name",
            }:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                rendered = value
            else:
                rendered = str(value)
            if lowered in SENSITIVE_KEYS:
                rendered = _mask_value(str(rendered))
            payload[key] = rendered
        return orjson.dumps(payload).decode("utf-8")


__all__ = ["configure_logging", "JSONLogFormatter"]
