from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    tokens = json.dumps(
        [
            {"value": "test-admin-token-123456", "role": "ADMIN"},
            {"value": "test-metrics-token-654321", "role": "METRICS_RO"},
        ],
        ensure_ascii=False,
    )
    signing_keys = json.dumps(
        [
            {"kid": "legacy", "secret": "A" * 48, "state": "retired"},
            {"kid": "active", "secret": "B" * 48, "state": "active"},
        ],
        ensure_ascii=False,
    )
    monkeypatch.setenv("TOKENS", tokens)
    monkeypatch.setenv("DOWNLOAD_SIGNING_KEYS", signing_keys)
    config_payload = {
        "redis": {"dsn": "redis://localhost:6379/0", "namespace": "test_order", "operation_timeout": 0.2},
        "database": {"dsn": "postgresql://localhost/test", "statement_timeout_ms": 500},
        "auth": {
            "metrics_token": "test-metrics-token-654321",
            "service_token": "test-admin-token-123456",
        },
        "timezone": "Asia/Tehran",
        "enable_debug_logs": False,
        "enable_diagnostics": True,
    }
    config = AppConfig.model_validate(config_payload)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    metrics = build_metrics("test_middleware")
    timer = DeterministicTimer([0.01, 0.01, 0.01])
    rate_store = InMemoryKeyValueStore("test:rate", clock)
    idem_store = InMemoryKeyValueStore("test:idem", clock)
    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
    )

    @app.post("/chain-check")
    async def _chain_check(request: Request) -> dict[str, object]:
        chain = list(getattr(request.state, "middleware_chain", []))
        return {"chain": chain}

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("idempotency_key", ["chain-test-key-0001"])
def test_middleware_chain_order(client: TestClient, idempotency_key: str) -> None:
    response = client.post(
        "/chain-check",
        headers={
            "Authorization": "Bearer test-admin-token-123456",
            "Idempotency-Key": idempotency_key,
            "X-Client-ID": "middleware-spec",
        },
        json={"ping": True},
    )
    assert response.status_code == 200, response.text
    chain = response.json()["chain"]
    assert chain[:3] == ["RateLimit", "Idempotency", "Auth"], chain
    diagnostics = client.app.state.diagnostics
    assert diagnostics["last_chain"][:3] == ["RateLimit", "Idempotency", "Auth"]

