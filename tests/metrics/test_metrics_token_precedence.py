from __future__ import annotations

import json
import os
from datetime import datetime
from hashlib import blake2s
from typing import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import (
    AppConfig,
    AuthConfig,
    DatabaseConfig,
    ObservabilityConfig,
    RateLimitConfig,
    RedisConfig,
)
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.app.utils import get_debug_context
from phase6_import_to_sabt.obs.metrics import build_metrics

_ANCHOR = "AGENTS.md::Middleware Order"
_MISSING_ERROR = "«پیکربندی ناقص است؛ متغیر METRICS_TOKEN یا IMPORT_TO_SABT_AUTH__METRICS_TOKEN را مقداردهی کنید.»"


def _namespace(seed: str) -> str:
    digest = blake2s(seed.encode("utf-8"), digest_size=6).hexdigest()
    return f"metrics-precedence-{digest}"


@pytest.fixture()
def metrics_client_builder(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    created_envs: list[str] = []

    def _build(
        *,
        env_token: str | None,
        config_token: str,
        metrics_env_token: str | None = None,
    ) -> TestClient:
        seed = os.environ.get("PYTEST_CURRENT_TEST", "metrics-precedence")
        namespace = _namespace(f"{seed}:{env_token}:{config_token}:{metrics_env_token}")
        tokens_env = f"TOKENS_{namespace.replace('-', '_')}"
        signing_env = f"SIGNING_{namespace.replace('-', '_')}"
        tokens_payload = [
            {"value": "svc-token-abcdef123456", "role": "ADMIN"},
        ]
        if metrics_env_token:
            tokens_payload.append(
                {
                    "value": metrics_env_token,
                    "role": "METRICS_RO",
                    "metrics_only": True,
                }
            )
        signing_payload = [
            {"kid": "active", "secret": "S" * 48, "state": "active"},
        ]
        monkeypatch.setenv(tokens_env, json.dumps(tokens_payload, ensure_ascii=False))
        monkeypatch.setenv(signing_env, json.dumps(signing_payload, ensure_ascii=False))
        created_envs.extend([tokens_env, signing_env])
        monkeypatch.delenv("METRICS_TOKEN", raising=False)
        if env_token is not None:
            monkeypatch.setenv("METRICS_TOKEN", env_token)
            created_envs.append("METRICS_TOKEN")

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
                metrics_token=config_token,
                service_token="svc-token-abcdef123456",
                tokens_env_var=tokens_env,
                download_signing_keys_env_var=signing_env,
                download_url_ttl_seconds=600,
            ),
            ratelimit=RateLimitConfig(
                namespace=namespace,
                requests=120,
                window_seconds=60,
                penalty_seconds=60,
            ),
            observability=ObservabilityConfig(
                service_name="metrics-precedence",
                metrics_namespace=namespace,
            ),
            timezone="Asia/Tehran",
            readiness_timeout_seconds=0.1,
            health_timeout_seconds=0.1,
            enable_debug_logs=False,
            enable_diagnostics=True,
        )
        registry = CollectorRegistry()
        metrics = build_metrics(namespace, registry=registry)
        timer = DeterministicTimer([0.001] * 32)
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
        return client

    yield _build

    for name in created_envs:
        monkeypatch.delenv(name, raising=False)


def _metrics_response(
    client: TestClient,
    token: str | None,
    *,
    authorization: str | None = None,
) -> tuple[int, dict[str, object]]:
    headers: dict[str, str] = {}
    if token is not None:
        headers["X-Metrics-Token"] = token
    if authorization:
        headers["Authorization"] = authorization
    response = client.get("/metrics", headers=headers)
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    return response.status_code, payload


def test_env_top_level_overrides_nested(metrics_client_builder) -> None:
    build_client = metrics_client_builder
    client = build_client(env_token="env-token-900", config_token="config-token-100")
    try:
        ctx = get_debug_context(client.app)
        ctx["evidence"] = _ANCHOR
        ok_status, _ = _metrics_response(client, "env-token-900")
        assert ok_status == 200, ctx
        bad_status, _ = _metrics_response(client, "config-token-100")
        ctx_forbidden = get_debug_context(client.app)
        ctx_forbidden["evidence"] = _ANCHOR
        assert bad_status in {401, 403}, ctx_forbidden
        diagnostics = client.app.state.diagnostics
        assert diagnostics["metrics_token_source"] == "env:METRICS_TOKEN", diagnostics
    finally:
        client.close()


def test_nested_config_used_when_env_missing(metrics_client_builder) -> None:
    build_client = metrics_client_builder
    client = build_client(env_token=None, config_token="config-only-token")
    try:
        status, payload = _metrics_response(client, "config-only-token")
        assert status == 200, payload
        diagnostics = client.app.state.diagnostics
        assert diagnostics["metrics_token_source"] == "config:IMPORT_TO_SABT_AUTH__METRICS_TOKEN", diagnostics
    finally:
        client.close()


def test_tokens_env_used_when_config_blank(metrics_client_builder) -> None:
    build_client = metrics_client_builder
    client = build_client(env_token=None, config_token="", metrics_env_token="metrics-env-token-4444")
    try:
        status, payload = _metrics_response(
            client,
            "metrics-env-token-4444",
            authorization="Bearer metrics-env-token-4444",
        )
        assert status == 200, payload
        diagnostics = client.app.state.diagnostics
        assert diagnostics["metrics_token_source"].startswith("env:TOKENS_"), diagnostics
    finally:
        client.close()


def test_missing_metrics_token_returns_persian_error(metrics_client_builder) -> None:
    build_client = metrics_client_builder
    client = build_client(env_token=None, config_token="")
    try:
        status, payload = _metrics_response(
            client,
            None,
            authorization="Bearer svc-token-abcdef123456",
        )
        assert status == 403, payload
        envelope = payload.get("fa_error_envelope", {})
        assert envelope.get("code") == "METRICS_TOKEN_MISSING", payload
        assert envelope.get("message") == _MISSING_ERROR, payload
        diagnostics = client.app.state.diagnostics
        assert diagnostics["metrics_token_error"] == _MISSING_ERROR, diagnostics
    finally:
        client.close()


def test_top_env_overrides_nested_and_missing_is_persian_403(metrics_client_builder) -> None:
    test_env_top_level_overrides_nested(metrics_client_builder)
    test_missing_metrics_token_returns_persian_error(metrics_client_builder)
