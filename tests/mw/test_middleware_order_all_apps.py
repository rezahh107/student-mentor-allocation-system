import asyncio
import json
import uuid
from datetime import datetime

import httpx
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.infrastructure.api.routes import create_app as create_infra_app
from src.phase6_import_to_sabt.app.app_factory import create_application
from src.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedisConfig,
)
from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from src.phase6_import_to_sabt.app.timing import DeterministicTimer
from src.phase6_import_to_sabt.obs.metrics import build_metrics


def _build_phase6_app(monkeypatch):
    namespace = f"phase6-test-{uuid.uuid4().hex}"
    tokens_env = f"TOKENS_{uuid.uuid4().hex}"
    signing_env = f"SIGNING_{uuid.uuid4().hex}"
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
        redis=RedisConfig(dsn="redis://localhost:6379/0", namespace=namespace, operation_timeout=0.1),
        database=DatabaseConfig(dsn="postgresql://localhost/test", statement_timeout_ms=500),
        auth=AuthConfig(
            metrics_token="metrics-token",
            service_token="service-token",
            tokens_env_var=tokens_env,
            download_signing_keys_env_var=signing_env,
            download_url_ttl_seconds=600,
        ),
        ratelimit=RateLimitConfig(namespace=namespace, requests=100, window_seconds=60, penalty_seconds=60),
        observability=ObservabilityConfig(service_name="phase6-test", metrics_namespace=namespace),
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
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
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
    assert response.status_code == 200
    chain = response.json()["middleware_chain"]
    assert chain[:3] == ["RateLimit", "Idempotency", "Auth"]


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
    assert response.status_code == 202
    chain_header = response.headers.get("X-Middleware-Chain")
    assert chain_header is not None
    assert chain_header.split(",")[:3] == ["RateLimit", "Idempotency", "Auth"]
