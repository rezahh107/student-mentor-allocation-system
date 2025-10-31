from __future__ import annotations

from typing import Any

try:  # pragma: no cover - optional dependency
    import uvloop
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    uvloop = None

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, generate_latest

from .clock import Clock
from .runtime import (
    ensure_agents_manifest,
    ensure_python_311,
    ensure_tehran_tz,
    is_uvloop_supported,
)
from .settings import AppSettings
from .state import InMemoryStore


def _maybe_install_uvloop() -> bool:
    if not is_uvloop_supported() or uvloop is None:
        return False
    uvloop.install()
    return True


def _build_middleware(app: FastAPI, settings: AppSettings) -> None:
    namespace = settings.redis.namespace
    app.state.rate_store = InMemoryStore(f"{namespace}:rate")
    app.state.idempotency_store = InMemoryStore(f"{namespace}:idempotency")


def create_application(settings: AppSettings | None = None) -> FastAPI:
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
    async def metrics() -> JSONResponse:
        payload = generate_latest(registry)
        content = {"prometheus": payload.decode("utf-8")}
        return JSONResponse(status_code=200, content=content)

    @app.post("/echo")
    async def echo(request: Request) -> JSONResponse:
        body = await request.json()
        response = {
            "clock": app.state.clock.now().isoformat(),
            "body": body,
            "diagnostics": [],
        }
        return JSONResponse(status_code=200, content=response)

    return app


__all__ = ["create_application"]
