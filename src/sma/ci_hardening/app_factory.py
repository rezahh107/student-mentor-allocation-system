"""Factory for the hardened FastAPI application used in CI tests."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, generate_latest

from .clock import Clock
from .middleware import (
    AuthConfig,
    AuthMiddleware,
    IdempotencyMiddleware,
    RateLimitConfig,
    RateLimitMiddleware,
    RateLimitRule,
)
from .retry import RetryConfig
from .runtime import (
    ensure_agents_manifest,
    ensure_python_311,
    ensure_tehran_tz,
    is_uvloop_supported,
)
from .settings import AppSettings
from .state import InMemoryStore


def _maybe_install_uvloop() -> bool:
    """Attempt to install ``uvloop`` when supported.

    Returns:
        ``True`` when ``uvloop`` was successfully installed; ``False`` when the
        platform does not support it or the dependency is unavailable.
    """

    if not is_uvloop_supported():
        return False
    try:  # pragma: no cover - platform specific
        import uvloop
    except ModuleNotFoundError:
        return False
    uvloop.install()
    return True


def _build_middleware(app: FastAPI, settings: AppSettings) -> None:
    """Register middleware ensuring deterministic execution order.

    Args:
        app: FastAPI application to configure.
        settings: Application settings providing namespaces and tokens.
    """

    rate_store = InMemoryStore(f"{settings.redis.namespace}:rate")
    idem_store = InMemoryStore(f"{settings.redis.namespace}:idempotency")
    retry = RetryConfig(
        max_attempts=settings.retry.max_attempts,
        base_delay=settings.retry.base_delay_seconds,
    )
    rate_config = RateLimitConfig(
        namespace=settings.redis.namespace,
        rules=(RateLimitRule(limit=2, window_seconds=60),),
    )
    allowed_tokens = [settings.auth.service_token]
    if settings.auth.metrics_token:
        allowed_tokens.append(settings.auth.metrics_token)
    app.add_middleware(
        AuthMiddleware,
        config=AuthConfig(allowed_tokens=tuple(allowed_tokens)),
    )
    app.add_middleware(IdempotencyMiddleware, store=idem_store)
    app.add_middleware(
        RateLimitMiddleware,
        store=rate_store,
        config=rate_config,
        retry=retry,
        registry=getattr(app.state, "registry", None),
    )
    app.state.rate_store = rate_store
    app.state.idempotency_store = idem_store


def _metrics_guard(x_metrics_token: str | None, settings: AppSettings) -> None:
    """Validate metrics access tokens before exposing Prometheus data.

    Args:
        x_metrics_token: Optional token provided by the client.
        settings: Application settings containing the expected token values.

    Raises:
        HTTPException: If the provided token does not match the expected value.
    """

    expected = settings.auth.metrics_token or settings.auth.service_token
    if not expected or x_metrics_token != expected:
        raise HTTPException(status_code=403, detail="توکن متریک نامعتبر است.")


def create_application(settings: AppSettings | None = None) -> FastAPI:
    """Create a FastAPI application with deterministic middleware ordering.

    Args:
        settings: Optional pre-loaded settings instance. When omitted the
            configuration is loaded from the environment.

    Returns:
        Configured FastAPI application ready for deterministic CI execution.
    """

    ensure_agents_manifest()
    ensure_python_311()
    tz = ensure_tehran_tz()
    settings = settings or AppSettings.load()
    clock = Clock(tz=tz)
    registry = CollectorRegistry()
    app = FastAPI(title="Student Mentor Allocation System")
    app.state.clock = clock
    app.state.registry = registry
    app.state.settings = settings
    app.state.uvloop_enabled = _maybe_install_uvloop()

    _build_middleware(app, settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "timezone": settings.timezone,
            "uvloop": app.state.uvloop_enabled,
        }

    @app.get("/metrics")
    async def metrics(
        x_metrics_token: str | None = Header(default=None),
    ) -> JSONResponse:
        _metrics_guard(x_metrics_token, settings)
        payload = generate_latest(registry)
        return JSONResponse(
            status_code=200,
            content={"prometheus": payload.decode("utf-8")},
        )

    @app.post("/echo")
    async def echo(request: Request) -> JSONResponse:
        diagnostics = getattr(request.state, "diagnostics", None)
        body = await request.json()
        response = {
            "clock": app.state.clock.now().isoformat(),
            "body": body,
            "diagnostics": diagnostics.order if diagnostics else [],
        }
        return JSONResponse(status_code=200, content=response)

    return app


__all__ = ["create_application"]
