"""JSON logging enrichers for attaching debug context snapshots."""
from __future__ import annotations

import json
import logging

from src.app.context import get_debug_context


class LogEnricher(logging.Filter):
    """Logging filter that injects the active debug context into records."""

    def __init__(self, *, field_name: str = "debug_context") -> None:
        super().__init__()
        self._field_name = field_name

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - exercised via tests
        payload = self._serialize_context()
        setattr(record, self._field_name, payload)
        return True

    def _serialize_context(self) -> str:
        ctx = get_debug_context()
        if ctx is None:
            return "{}"
        try:
            return ctx.as_json()
        except Exception:
            return json.dumps({"error": "context_unavailable"}, ensure_ascii=False, sort_keys=True)


def register_log_enricher(logger: logging.Logger, *, field_name: str = "debug_context") -> LogEnricher:
    """Attach the :class:`LogEnricher` filter to the provided logger."""

    for existing in logger.filters:
        if isinstance(existing, LogEnricher) and getattr(existing, "_field_name", field_name) == field_name:
            return existing
    enricher = LogEnricher(field_name=field_name)
    logger.addFilter(enricher)
    for handler in list(logger.handlers):
        handler.addFilter(enricher)
    return enricher


__all__ = ["LogEnricher", "register_log_enricher"]
