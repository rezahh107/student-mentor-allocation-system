from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from starlette.requests import Request

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.probes import ProbeResult


def _base_config() -> AppConfig:
    return AppConfig(
        redis={"dsn": "redis://localhost:6379/0"},
        database={"dsn": "postgresql://postgres:postgres@localhost:5432/postgres"},
        auth={
            "service_token": "service-token-1234567890",
            "metrics_token": "metrics-token-1234567890",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )


def test_readyz_reports_failure_with_components() -> None:
    async def _run() -> None:
        async def redis_ok(_: float) -> ProbeResult:
            return ProbeResult(component="redis", healthy=True)

        async def postgres_fail(_: float) -> ProbeResult:
            return ProbeResult(component="postgres", healthy=False, detail="boom")

        app = create_application(config=_base_config(), readiness_probes={"redis": redis_ok, "postgres": postgres_fail})
        endpoint = _resolve_readyz(app)
        response = await endpoint(_build_request())

        assert response.status_code == 503
        payload = json.loads(response.body.decode("utf-8"))
        assert payload["redis"] == "ok"
        assert payload["postgres"] == "fail"
        assert payload["status"] == "fail"
        assert "message" in payload

    asyncio.run(_run())


def test_readyz_returns_ok_when_all_components_healthy() -> None:
    async def _run() -> None:
        async def redis_ok(_: float) -> ProbeResult:
            return ProbeResult(component="redis", healthy=True)

        async def postgres_ok(_: float) -> ProbeResult:
            return ProbeResult(component="postgres", healthy=True)

        app = create_application(config=_base_config(), readiness_probes={"redis": redis_ok, "postgres": postgres_ok})
        endpoint = _resolve_readyz(app)
        response = await endpoint(_build_request())

        assert response.status_code == 200
        payload = json.loads(response.body.decode("utf-8"))
        assert payload["redis"] == "ok"
        assert payload["postgres"] == "ok"
        assert payload["status"] == "ok"

    asyncio.run(_run())


def _resolve_readyz(app) -> Callable[[Request], Awaitable[object]]:
    for route in app.routes:
        if getattr(route, "path", "") == "/readyz":
            return route.endpoint
    raise AssertionError("readyz route not registered")


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/readyz",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)
