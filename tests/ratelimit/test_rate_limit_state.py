"""Rate limit state validation referencing AGENTS.md::Middleware Order."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime

import httpx
import pytest
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.phase6_import_to_sabt.app.app_factory import create_application
from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedisConfig,
)
from src.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from src.phase6_import_to_sabt.app.timing import DeterministicTimer
from src.phase6_import_to_sabt.obs.metrics import build_metrics
from src.ops.ratelimit_metrics import build_rate_limit_metrics

_ANCHOR = "AGENTS.md::Middleware Order"
_EXPECTED_CHAIN = ["RateLimit", "Idempotency", "Auth"]


def _build_rate_limited_app(monkeypatch, *, capacity: int, window: int = 60):
    namespace = f"ratelimit-{uuid.uuid4().hex}"
    tokens_env = f"TOKENS_{uuid.uuid4().hex}"
    signing_env = f"SIGNING_{uuid.uuid4().hex}"
    tokens_payload = [{"value": "T" * 32, "role": "ADMIN"}]
    signing_payload = [{"kid": "primary", "secret": "S" * 48, "state": "active"}]
    monkeypatch.setenv(tokens_env, json.dumps(tokens_payload, ensure_ascii=False))
    monkeypatch.setenv(signing_env, json.dumps(signing_payload, ensure_ascii=False))

    registry = CollectorRegistry()
    metrics = build_metrics(namespace, registry=registry)
    clock = FixedClock(datetime(2024, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Tehran")))
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
        ratelimit=RateLimitConfig(
            namespace=namespace,
            requests=capacity,
            window_seconds=window,
            penalty_seconds=window,
        ),
        observability=ObservabilityConfig(service_name="ratelimit-test", metrics_namespace=namespace),
        timezone="Asia/Tehran",
        readiness_timeout_seconds=0.1,
        health_timeout_seconds=0.1,
        enable_debug_logs=True,
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

    return namespace, registry, app


def _send_request(app, **kwargs):
    async def _call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post(**kwargs)

    return asyncio.run(_call())


def test_rate_limit_tokens_and_drops(monkeypatch) -> None:
    namespace, registry, app = _build_rate_limited_app(monkeypatch, capacity=2, window=30)
    rate_metrics = build_rate_limit_metrics(namespace, registry=registry)
    assert rate_metrics.namespace == namespace

    headers = {
        "Authorization": "Bearer " + "T" * 32,
        "Idempotency-Key": "idem-ratelimit",
        "X-Client-ID": "ratelimit-client",
    }

    first = _send_request(app, url="/api/jobs", json={}, headers=headers)
    assert first.status_code == 200, {
        "anchor": _ANCHOR,
        "status": first.status_code,
        "body": first.json(),
    }
    chain = first.json()["middleware_chain"]
    assert chain[:3] == _EXPECTED_CHAIN, {"anchor": _ANCHOR, "chain": chain}
    remaining_header = int(first.headers.get("X-RateLimit-Remaining", "-1"))
    assert remaining_header == 1, {"anchor": _ANCHOR, "remaining": remaining_header}

    second = _send_request(app, url="/api/jobs", json={}, headers=headers)
    assert second.status_code == 200, {
        "anchor": _ANCHOR,
        "status": second.status_code,
        "body": second.json(),
    }
    assert int(second.headers.get("X-RateLimit-Remaining", "-1")) == 0, {
        "anchor": _ANCHOR,
        "headers": dict(second.headers),
    }

    third = _send_request(app, url="/api/jobs", json={}, headers=headers)
    assert third.status_code == 429, {
        "anchor": _ANCHOR,
        "status": third.status_code,
        "body": third.json(),
    }

    gauge_value = registry.get_sample_value(
        f"{namespace}_ratelimit_tokens",
        {"route": "/api/jobs"},
    )
    drop_value = registry.get_sample_value(
        f"{namespace}_ratelimit_drops_total",
        {"route": "/api/jobs"},
    )

    assert gauge_value == pytest.approx(0.0), {
        "anchor": _ANCHOR,
        "gauge": gauge_value,
        "drops": drop_value,
    }
    assert drop_value == pytest.approx(1.0), {"anchor": _ANCHOR, "drops": drop_value}
