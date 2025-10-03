"""Deterministic middleware wiring ensuring RateLimit → Idempotency → Auth order."""
from __future__ import annotations

from typing import Iterable

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from .middleware import (
    AuthenticationMiddleware,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
    MiddlewareState,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TraceProbeMiddleware,
)

POST_CHAIN = ("RateLimit", "Idempotency", "Auth")
GET_CHAIN = ("RateLimit", "Auth")


def install_middleware_chain(
    app: ASGIApp,
    *,
    state: MiddlewareState,
    allowed_origins: Iterable[str],
) -> None:
    """Install middleware in deterministic order with optional tracing support."""

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["POST", "GET"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-Request-ID",
            "Idempotency-Key",
            "X-Debug-MW-Probe",
        ],
        expose_headers=["X-Correlation-ID", "Retry-After", "X-RateLimit-Remaining", "X-MW-Trace"],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(AuthenticationMiddleware, state=state)
    app.add_middleware(IdempotencyMiddleware, state=state)
    app.add_middleware(RateLimitMiddleware, state=state)
    app.add_middleware(TraceProbeMiddleware)

    state_attr = getattr(app, "state", None)
    if state_attr is not None:
        declared = tuple(m.cls.__name__ for m in getattr(app, "user_middleware", ()))
        setattr(state_attr, "middleware_declared_order", declared)
        setattr(state_attr, "middleware_post_chain", POST_CHAIN)
        setattr(state_attr, "middleware_get_chain", GET_CHAIN)


__all__ = ["install_middleware_chain", "POST_CHAIN", "GET_CHAIN"]
