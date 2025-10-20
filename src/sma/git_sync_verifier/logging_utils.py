"""Structured logging helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "correlation_id"):
            payload["correlation_id"] = getattr(record, "correlation_id")
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.__dict__:
            extras = {
                key: value
                for key, value in record.__dict__.items()
                if key not in ("args", "name", "msg", "levelname", "levelno")
            }
            if extras:
                payload.update(extras)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(correlation_id: str) -> logging.Logger:
    """Configure root logger for deterministic JSON logging."""
    logger = logging.getLogger("git_sync_verifier")
    if logger.handlers:
        for handler in logger.handlers:
            handler.setFormatter(JsonFormatter())
        logger.setLevel(logging.INFO)
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger = logging.LoggerAdapter(logger, {"correlation_id": correlation_id})
    return logger  # type: ignore[return-value]


def mask_path(path: Path) -> str:
    """Mask sensitive parts of a path by hashing."""
    normalized = os.fspath(path)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"hash:{digest[:16]}"
