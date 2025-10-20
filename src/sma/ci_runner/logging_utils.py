"""Structured logging helpers with PII masking and bilingual messaging."""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Dict

import structlog

_CORRELATION_ENV = "CI_CORRELATION_ID"
_CONFIGURED = False

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b09\d{9}\b"),
    re.compile(r"\b\d{10}\b"),
    re.compile(r"\b\d{16}\b"),
    re.compile(r"\bIR\d{24}\b", re.IGNORECASE),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"(?i)token\s*[:=]\s*[A-Za-z0-9._-]+"),
)


def _mask_value(value: str) -> str:
    masked = value
    for pattern in _PII_PATTERNS:
        masked = pattern.sub("[REDACTED]", masked)
    return masked


def _mask_event(_: structlog.types.WrappedLogger, __: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = _mask_value(value)
        elif isinstance(value, (list, tuple)):
            event_dict[key] = [
                _mask_value(item) if isinstance(item, str) else item for item in value
            ]
    return event_dict


def correlation_id() -> str:
    cid = os.getenv(_CORRELATION_ENV)
    if cid:
        return cid
    if os.getenv("GITHUB_RUN_ID"):
        cid = f"gha-{os.getenv('GITHUB_RUN_ID')}"
    else:
        cid = f"local-{uuid.uuid4()}"
    os.environ[_CORRELATION_ENV] = cid
    return cid


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    def _add_correlation(_: structlog.types.WrappedLogger, __: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        event_dict.setdefault("correlation_id", correlation_id())
        return event_dict

    structlog.configure(
        processors=[
            _add_correlation,
            structlog.processors.add_log_level,
            _mask_event,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger() -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger()


def bilingual_message(persian: str, english: str) -> str:
    return f"{persian} :: {english}"


def log_event(message: str, **extra: Any) -> None:
    logger = get_logger()
    logger.info(message, **extra)
