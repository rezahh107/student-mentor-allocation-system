from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from sma.phase6_import_to_sabt.app.clock import Clock
from sma.phase6_import_to_sabt.app.timing import Timer
from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation-id header to every request."""

    def __init__(self, app: ASGIApp, clock: Clock) -> None:  # type: ignore[override]
        super().__init__(app)
        self._clock = clock

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        header_value = request.headers.get("X-Request-ID")
        correlation_id = header_value or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        request.state.request_ts = self._clock.now()
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect simple request metrics without any auth enforcement."""

    def __init__(self, app: ASGIApp, metrics: ServiceMetrics, timer: Timer) -> None:  # type: ignore[override]
        super().__init__(app)
        self._metrics = metrics
        self._timer = timer

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        handle = self._timer.start()
        response = await call_next(request)
        duration = handle.elapsed()
        self._metrics.request_latency.observe(duration)
        self._metrics.request_total.labels(
            method=request.method,
            path=request.url.path,
            status=str(response.status_code),
        ).inc()
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log high-level request outcomes for observability."""

    def __init__(
        self,
        app: ASGIApp,
        diagnostics: Callable[[], dict[str, object] | None],
    ) -> None:  # type: ignore[override]
        super().__init__(app)
        self._diagnostics_factory = diagnostics

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        logger.info(
            "request.completed",
            extra={
                "correlation_id": getattr(request.state, "correlation_id", None),
                "component": "http",
                "outcome": response.status_code,
            },
        )
        diagnostics = self._diagnostics_factory()
        if diagnostics and diagnostics.get("enabled"):
            diagnostics["last_chain"] = []
        return response


__all__ = [
    "CorrelationIdMiddleware",
    "MetricsMiddleware",
    "RequestLoggingMiddleware",
]
