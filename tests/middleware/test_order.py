from __future__ import annotations

import json
import json
import os
from datetime import datetime, timezone
from hashlib import blake2s
from typing import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics

_ANCHOR = "AGENTS.md::Middleware Order"


def _unique_namespace(seed: str) -> str:
    digest = blake2s(seed.encode("utf-8"), digest_size=6).hexdigest()
    return f"middleware-order-{digest}"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    seed = os.environ.get("PYTEST_CURRENT_TEST", "middleware-order")
    namespace = _unique_namespace(seed)
    tokens_env = f"TOKENS_{namespace.replace('-', '_')}"
    signing_env = f"SIGNING_{namespace.replace('-', '_')}"
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
    monkeypatch.setenv(tokens_env, tokens)
    monkeypatch.setenv(signing_env, signing_keys)
    config_payload = {
        "redis": {
            "dsn": "redis://localhost:6379/0",
            "namespace": namespace,
            "operation_timeout": 0.2,
        },
        "database": {"dsn": "postgresql://localhost/test", "statement_timeout_ms": 500},
        "auth": {
            "metrics_token": "test-metrics-token-654321",
            "service_token": "test-admin-token-123456",
            "tokens_env_var": tokens_env,
            "download_signing_keys_env_var": signing_env,
        },
        "timezone": "Asia/Tehran",
        "enable_debug_logs": False,
        "enable_diagnostics": True,
    }
    config = AppConfig.model_validate(config_payload)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    registry = CollectorRegistry()
    metrics = build_metrics(namespace, registry=registry)
    timer = DeterministicTimer([0.01, 0.01, 0.01])
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

    @app.post("/chain-check")
    async def _chain_check(request: Request) -> dict[str, object]:
        chain = list(getattr(request.state, "middleware_chain", []))
        debug = getattr(request.app.state, "diagnostics", {})
        return {"chain": chain, "debug": debug}

    with TestClient(app) as test_client:
        yield test_client
    monkeypatch.delenv(tokens_env, raising=False)
    monkeypatch.delenv(signing_env, raising=False)


@pytest.mark.parametrize("idempotency_key", ["chain-test-key-0001"])
def test_middleware_order_rate_limit_then_idempotency_then_auth(
    client: TestClient, idempotency_key: str
) -> None:
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
    diagnostics = client.app.state.diagnostics
    context = {"chain": chain, "diagnostics": diagnostics, "evidence": _ANCHOR}
    assert chain[:3] == ["RateLimit", "Idempotency", "Auth"], context
    assert diagnostics["last_chain"][:3] == ["RateLimit", "Idempotency", "Auth"], context


def test_middleware_order_not_regressed(client: TestClient) -> None:
    test_middleware_order_rate_limit_then_idempotency_then_auth(
        client,
        "chain-test-key-0002",
    )

