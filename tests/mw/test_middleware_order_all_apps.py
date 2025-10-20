import asyncio
import json
import os
from datetime import datetime
from hashlib import blake2s
from zoneinfo import ZoneInfo

import httpx
from prometheus_client import CollectorRegistry

from sma.infrastructure.api.routes import create_app as create_infra_app
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

_ANCHOR = "AGENTS.md::Middleware Order"
_SUCCESS_STATUS = 200
_ACCEPTED_STATUS = 202
_EXPECTED_CHAIN = ["RateLimit", "Idempotency", "Auth"]


def _deterministic_hex(seed: str) -> str:
    return blake2s(seed.encode("utf-8"), digest_size=6).hexdigest()


def _build_phase6_app(monkeypatch):
    seed = os.environ.get("PYTEST_CURRENT_TEST", "phase6-app")
    namespace = f"phase6-test-{_deterministic_hex(seed + ':namespace')}"
    tokens_env = f"TOKENS_{_deterministic_hex(seed + ':tokens')}"
    signing_env = f"SIGNING_{_deterministic_hex(seed + ':signing')}"
    tokens_payload = [
        {"value": "service-token", "role": "ADMIN"},
        {"value": "metrics-token", "role": "METRICS_RO", "metrics_only": True},
    ]
    signing_payload = [{"kid": "primary", "value": "secret", "status": "active"}]
    monkeypatch.setenv(tokens_env, json.dumps(tokens_payload, ensure_ascii=False))
    monkeypatch.setenv(signing_env, json.dumps(signing_payload, ensure_ascii=False))

    registry = CollectorRegistry()
    metrics = build_metrics(namespace, registry=registry)
    clock = FixedClock(datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Tehran")))
    timer = DeterministicTimer([0.001] * 32)
    rate_store = InMemoryKeyValueStore(namespace=f"{namespace}:rate", clock=clock)
    idem_store = InMemoryKeyValueStore(namespace=f"{namespace}:idem", clock=clock)

    config = AppConfig(
        redis=RedisConfig(
            dsn="redis://localhost:6379/0",
            namespace=namespace,
            operation_timeout=0.1,
        ),
        database=DatabaseConfig(
            dsn="postgresql://localhost/test",
            statement_timeout_ms=500,
        ),
        auth=AuthConfig(
            metrics_token="metrics-token",
            service_token="service-token",
            tokens_env_var=tokens_env,
            download_signing_keys_env_var=signing_env,
            download_url_ttl_seconds=600,
        ),
        ratelimit=RateLimitConfig(
            namespace=namespace,
            requests=100,
            window_seconds=60,
            penalty_seconds=60,
        ),
        observability=ObservabilityConfig(
            service_name="phase6-test",
            metrics_namespace=namespace,
        ),
        timezone="Asia/Tehran",
        readiness_timeout_seconds=0.1,
        health_timeout_seconds=0.1,
        enable_debug_logs=False,
        enable_diagnostics=True,
    )

    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
        workflow=None,
    )
    return app


def _send_request(app, method: str, path: str, **kwargs):
    async def _call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_call())


def test_order_phase6_app(monkeypatch) -> None:
    app = _build_phase6_app(monkeypatch)
    response = _send_request(
        app,
        "POST",
        "/api/jobs",
        headers={
            "Authorization": "Bearer service-token",
            "Idempotency-Key": "idem-phase6",
            "X-Client-ID": "tester",
        },
        json={},
    )
    assert response.status_code == _SUCCESS_STATUS, _failure_context(response)
    chain = response.json()["middleware_chain"]
    assert chain[:3] == _EXPECTED_CHAIN, _failure_context(response, chain=chain)


def test_order_infra_app(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "infra-metrics")
    infra_app = create_infra_app()
    response = _send_request(
        infra_app,
        "POST",
        "/api/v1/allocation/run",
        json={"priority_mode": "normal", "guarantee_assignment": False},
        headers={
            "Authorization": "Bearer demo-token",
            "X-Roles": "alloc:run",
            "Idempotency-Key": "infra-idem",
            "X-Api-Key": "infra-client",
        },
    )
    assert response.status_code == _ACCEPTED_STATUS, _failure_context(response)
    chain_header = response.headers.get("X-Middleware-Chain")
    assert chain_header is not None, _failure_context(response)
    chain_values = chain_header.split(",")
    assert chain_values[:3] == _EXPECTED_CHAIN, _failure_context(response, chain=chain_values)


def _failure_context(response, *, chain=None):
    payload = {
        "evidence": _ANCHOR,
        "status": response.status_code,
        "headers": dict(response.headers),
    }
    if chain is not None:
        payload["chain"] = chain
    return json.dumps(payload, ensure_ascii=False)
