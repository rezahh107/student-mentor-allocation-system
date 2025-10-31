from __future__ import annotations

from collections.abc import Callable, Iterator
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedisConfig,
)
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture(name="metrics_client_builder")
def _metrics_client_builder(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], TestClient]]:
    clients: list[TestClient] = []

    def _build(metrics_token: str) -> TestClient:
        monkeypatch.setenv("METRICS_ENDPOINT_ENABLED", "true")
        safe_token = metrics_token or "blank"
        safe_token = re.sub(r"[^a-zA-Z0-9_]", "_", safe_token)
        namespace = f"metrics_public_{safe_token}"
        config = AppConfig(
            redis=RedisConfig(
                dsn="redis://localhost:6379/0",
                namespace=f"{namespace}:redis",
                operation_timeout=0.1,
            ),
            database=DatabaseConfig(
                dsn="postgresql://localhost/test",
                statement_timeout_ms=500,
            ),
            auth=AuthConfig(
                metrics_token=metrics_token,
                service_token="svc-token",
            ),
            ratelimit=RateLimitConfig(
                namespace=f"{namespace}:ratelimit",
                requests=120,
                window_seconds=60,
                penalty_seconds=60,
            ),
            observability=ObservabilityConfig(
                service_name="metrics-public",
                metrics_namespace=f"{namespace}_metrics",
            ),
            timezone="Asia/Tehran",
            readiness_timeout_seconds=0.1,
            health_timeout_seconds=0.1,
            enable_debug_logs=False,
            enable_diagnostics=True,
        )
        registry = CollectorRegistry()
        metrics = build_metrics(config.observability.metrics_namespace, registry=registry)
        timer = DeterministicTimer([0.001] * 16)
        clock = FixedClock(datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tehran")))
        rate_store = InMemoryKeyValueStore(f"{namespace}:rate", clock)
        idem_store = InMemoryKeyValueStore(f"{namespace}:idem", clock)
        app = create_application(
            config,
            clock=clock,
            metrics=metrics,
            timer=timer,
            rate_limit_store=rate_store,
            idempotency_store=idem_store,
        )
        client = TestClient(app)
        clients.append(client)
        return client

    yield _build

    for client in clients:
        client.close()


def test_metrics_accessible_without_token(metrics_client_builder: Callable[[str], TestClient]) -> None:
    client = metrics_client_builder("configured-token")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text.startswith("# HELP")


def test_metrics_accessible_when_tokens_blank(metrics_client_builder: Callable[[str], TestClient]) -> None:
    client = metrics_client_builder("")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text.startswith("# HELP")
