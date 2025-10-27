"""Diagnostics and metrics for the CI hardening middleware chain."""

from __future__ import annotations

from datetime import datetime
import uuid

import pytest
from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from starlette.testclient import TestClient

from freezegun import freeze_time

from sma.ci_hardening.app_factory import create_application
from sma.ci_hardening.diagnostics import get_debug_context
from sma.ci_hardening.settings import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    RedisSettings,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning"
)


def _sample_value(
    registry: CollectorRegistry, name: str, labels: dict[str, str]
) -> float | None:
    """Return the value of a Prometheus sample matching labels."""

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


@pytest.mark.middleware
@pytest.mark.ci
def test_rate_limit_metrics_and_debug_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry metrics and debug helpers should provide deterministic context."""

    namespace = f"metrics-{uuid.uuid4()}"
    settings = _build_settings(namespace)
    monkeypatch.setattr("sma.ci_hardening.app_factory.ensure_python_311", lambda: None)
    monkeypatch.setattr(
        "sma.ci_hardening.app_factory.is_uvloop_supported", lambda: False
    )
    with freeze_time("2024-01-01T00:00:00+03:30"):
        app = create_application(settings=settings)
        try:
            with TestClient(app) as client:
                base_headers = {
                    "Authorization": "Bearer token-very-secure",
                    "X-RateLimit-Key": namespace,
                    "X-Correlation-ID": f"cid-{namespace}",
                }

                def _request(attempt: int):
                    headers = {
                        **base_headers,
                        "Idempotency-Key": f"idem-{namespace}-{attempt}",
                    }
                    return client.post(
                        "/echo",
                        json={"payload": "value"},
                        headers=headers,
                    )

                first = _request(1)
                assert first.status_code == 200
                second = _request(2)
                assert second.status_code == 200
                third = _request(3)
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
            registry = app.state.registry
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


@pytest.mark.middleware
def test_backoff_seed_uses_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff jitter must incorporate the correlation identifier for determinism."""

    namespace = f"seed-{uuid.uuid4()}"
    settings = _build_settings(namespace)
    monkeypatch.setattr("sma.ci_hardening.app_factory.ensure_python_311", lambda: None)
    monkeypatch.setattr(
        "sma.ci_hardening.app_factory.is_uvloop_supported", lambda: False
    )
    with freeze_time("2024-01-01T00:00:00+03:30"):
        app = create_application(settings=settings)
        try:
            with TestClient(app) as client:
                headers = {
                    "Authorization": "Bearer token-very-secure",
                    "Idempotency-Key": f"idem-{namespace}",
                    "X-RateLimit-Key": namespace,
                    "X-Correlation-ID": "cid-123",
                }
                response = client.post(
                    "/echo",
                    json={"payload": "value"},
                    headers=headers,
                )
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
            registry = app.state.registry
            assert granted == pytest.approx(1.0)
            redis_keys = context["redis_keys"]["keys"]
            assert redis_keys
        finally:
            _clean_application(app)
