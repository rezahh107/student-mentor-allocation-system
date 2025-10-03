# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any, Dict
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.clock import SupportsNow, tehran_clock

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def configure_json_logging(level: int = logging.INFO, *, clock: SupportsNow | None = None) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter(clock=clock))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, clock: SupportsNow | None = None) -> None:
        super().__init__()
        self._clock = clock or tehran_clock()

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        payload: Dict[str, Any] = {
            "ts": self._clock.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        corr = request.headers.get("X-Correlation-ID") or str(uuid4())
        token = correlation_id_var.set(corr)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr
            return response
        finally:
            correlation_id_var.reset(token)

