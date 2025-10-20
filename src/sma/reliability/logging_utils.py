from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping


correlation_id_var: ContextVar[str] = ContextVar("reliability_correlation_id", default="-")


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_DeterministicFormatter())
    root = logging.getLogger("reliability")
    root.setLevel(level)
    root.handlers = [handler]


class _DeterministicFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting only
        payload = {
            "ts": getattr(record, "ts", None),
            "level": record.levelname,
            "event": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        extra = getattr(record, "extra", None)
        if isinstance(extra, Mapping):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(slots=True)
class JSONLogger:
    name: str

    def bind(self, correlation_id: str) -> "JSONLoggerAdapter":
        return JSONLoggerAdapter(logging.getLogger(self.name), correlation_id)


class JSONLoggerAdapter:
    def __init__(self, logger: logging.Logger, correlation_id: str) -> None:
        self.logger = logger
        self.correlation_id = correlation_id or "-"

    def _log(self, level: int, event: str, **fields: Any) -> None:
        token = correlation_id_var.set(self.correlation_id)
        try:
            safe_fields = {key: mask_value(value) for key, value in fields.items()}
            payload = {
                "extra": safe_fields,
                "ts": fields.get("ts"),
            }
            self.logger.log(level, event, extra=payload)
        finally:
            correlation_id_var.reset(token)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)


def mask_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return value
        if len(value) <= 6:
            return value[0] + "***"
        digest = sha256(value.encode("utf-8")).hexdigest()
        return f"hash:{digest[:8]}"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Mapping):
        return {key: mask_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [mask_value(item) for item in value]
    return str(value)


def persian_error(message: str, code: str, *, correlation_id: str, details: Any | None = None) -> Mapping[str, Any]:
    payload = {
        "خطا": message,
        "کد": code,
        "correlation_id": correlation_id,
    }
    if details is not None:
        payload["جزئیات"] = details
    return payload


__all__ = ["JSONLogger", "configure_logging", "persian_error"]
