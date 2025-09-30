"""Bootstrap structured logging with optional debug context enrichment."""
from __future__ import annotations

import logging
import os

from src.logging.json_logger import register_log_enricher

_ENV_FLAG = "DEBUG_CONTEXT_ENABLE"


def bootstrap_logging(*, enable: bool | None = None) -> None:
    """Configure root logging handlers with the debug context enricher."""

    if not _should_enable(enable):
        return
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(handler)
    register_log_enricher(root_logger)


def _should_enable(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    raw = os.getenv(_ENV_FLAG)
    if raw is not None:
        return raw.lower() in {"1", "true", "yes", "on"}
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


__all__ = ["bootstrap_logging"]
