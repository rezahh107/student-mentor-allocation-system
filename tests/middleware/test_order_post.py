"""Middleware ordering guarantees for POST endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from freezegun import freeze_time
from sma.ci_hardening.app_factory import create_application
from sma.ci_hardening.settings import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    RedisSettings,
)


def _build_settings(namespace: str) -> AppSettings:
    return AppSettings(
        redis=RedisSettings(host="localhost", port=6379, db=0, namespace=namespace),
        database=DatabaseSettings(
            dsn="postgresql+psycopg://user:pass@localhost:5432/app"
        ),
        auth=AuthSettings(
            service_token="token-very-secure",
            metrics_token="metrics-token-secure",
        ),
    )


def _clean_application(app: FastAPI) -> None:
    app.state.rate_store.flush()
    app.state.idempotency_store.flush()


def test_middleware_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rate limit must execute before idempotency and auth on POST."""

    namespace = f"middleware-{uuid.uuid4()}"
    settings = _build_settings(namespace)
    monkeypatch.setattr("sma.ci_hardening.app_factory.ensure_python_311", lambda: None)
    monkeypatch.setattr(
        "sma.ci_hardening.app_factory.is_uvloop_supported", lambda: False
    )
    with freeze_time("2024-01-01T00:00:00+03:30"):
        app = create_application(settings=settings)
        with TestClient(app) as client:
            response = client.post(
                "/echo",
                json={"payload": "value"},
                headers={
                    "Authorization": "Bearer token-very-secure",
                    "Idempotency-Key": f"test-{namespace}",
                    "X-RateLimit-Key": namespace,
                },
            )
    try:
        assert response.status_code == 200, response.json()
        diagnostics = response.json()["diagnostics"]
        assert diagnostics == ["RateLimit", "Idempotency", "Auth"]
    finally:
        _clean_application(app)
