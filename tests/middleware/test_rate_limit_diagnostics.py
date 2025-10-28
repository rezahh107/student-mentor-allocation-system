import asyncio
from datetime import datetime
import uuid

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from freezegun import freeze_time

from sma.ci_hardening.app_factory import create_application
from sma.ci_hardening.diagnostics import get_debug_context
from sma.ci_hardening.settings import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    RedisSettings,
)


def _sample_value(
    registry: CollectorRegistry, name: str, labels: dict[str, str]
) -> float | None:
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name != name:
                continue
            if all(sample.labels.get(key) == value for key, value in labels.items()):
                return float(sample.value)
    return None


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


async def _exercise_requests(app: FastAPI, namespace: str, base_headers: dict[str, str]):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = []
        for attempt in (1, 2, 3):
            headers = {
                **base_headers,
                "Idempotency-Key": f"idem-{namespace}-{attempt}",
            }
            responses.append(
                await client.post("/echo", json={"payload": "value"}, headers=headers)
            )
        return responses


@pytest.mark.middleware
@pytest.mark.ci
def test_rate_limit_metrics_and_debug_context(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = f"metrics-{uuid.uuid4()}"
    settings = _build_settings(namespace)
    monkeypatch.setattr("sma.ci_hardening.app_factory.ensure_python_311", lambda: None)
    monkeypatch.setattr(
        "sma.ci_hardening.app_factory.is_uvloop_supported", lambda: False
    )
    with freeze_time("2024-01-01T00:00:00+03:30"):
        app = create_application(settings=settings)
        try:
            base_headers = {
                "Authorization": "Bearer token-very-secure",
                "X-RateLimit-Key": namespace,
                "X-Correlation-ID": f"cid-{namespace}",
            }
            first, second, third = asyncio.run(
                _exercise_requests(app, namespace, base_headers)
            )
            assert first.status_code == 200
            assert second.status_code == 200
            assert third.status_code == 429
            registry: CollectorRegistry = app.state.registry
            attempts = _sample_value(
                registry,
                "ci_rate_limit_attempts_total",
                {"namespace": namespace, "status": "attempt"},
            )
            granted = _sample_value(
                registry,
                "ci_rate_limit_attempts_total",
                {"namespace": namespace, "status": "granted"},
            )
            exhausted = _sample_value(
                registry,
                "ci_rate_limit_attempts_total",
                {"namespace": namespace, "status": "exhausted"},
            )
            expected_timestamp = app.state.clock.now().isoformat()
            context = get_debug_context(app, correlation_id=f"cid-{namespace}")
            assert attempts == pytest.approx(5.0)
            assert granted == pytest.approx(2.0)
            assert exhausted == pytest.approx(1.0)
            assert context["middleware_order"] == [
                "RateLimitMiddleware",
                "IdempotencyMiddleware",
                "AuthMiddleware",
            ]
            assert context["redis_keys"]["namespace"].startswith(namespace)
            assert context["env"] in {"true", "false", "local"}
            observed = datetime.fromisoformat(context["timestamp"])
            expected = datetime.fromisoformat(expected_timestamp)
            assert abs((observed - expected).total_seconds()) < 1
            assert context["correlation_id"] == f"cid-{namespace}"
        finally:
            _clean_application(app)


async def _exercise_single_request(app: FastAPI, headers: dict[str, str]):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/echo", json={"payload": "value"}, headers=headers)


@pytest.mark.middleware
def test_backoff_seed_uses_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = f"seed-{uuid.uuid4()}"
    settings = _build_settings(namespace)
    monkeypatch.setattr("sma.ci_hardening.app_factory.ensure_python_311", lambda: None)
    monkeypatch.setattr(
        "sma.ci_hardening.app_factory.is_uvloop_supported", lambda: False
    )
    with freeze_time("2024-01-01T00:00:00+03:30"):
        app = create_application(settings=settings)
        try:
            headers = {
                "Authorization": "Bearer token-very-secure",
                "Idempotency-Key": f"idem-{namespace}",
                "X-RateLimit-Key": namespace,
                "X-Correlation-ID": "cid-123",
            }
            response = asyncio.run(_exercise_single_request(app, headers))
            assert response.status_code == 200
            diagnostics = response.json()["diagnostics"]
            assert diagnostics == ["RateLimit", "Idempotency", "Auth"]
            registry: CollectorRegistry = app.state.registry
            granted = _sample_value(
                registry,
                "ci_rate_limit_attempts_total",
                {"namespace": namespace, "status": "granted"},
            )
            context = get_debug_context(app, correlation_id="cid-123")
            assert granted == pytest.approx(1.0)
            redis_keys = context["redis_keys"]["keys"]
            assert redis_keys
        finally:
            _clean_application(app)
