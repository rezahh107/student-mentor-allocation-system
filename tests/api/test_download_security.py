import base64
import datetime as dt
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.app.utils import get_debug_context
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture
def download_security_client(tmp_path):
    metrics_token = f"metrics-{uuid4().hex}"
    service_token = f"service-{uuid4().hex}"
    namespace = f"test:{uuid4().hex}"
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": namespace, "operation_timeout": 0.2},
        database={"dsn": "postgresql+asyncpg://localhost/test"},
        auth={
            "metrics_token": metrics_token,
            "service_token": service_token,
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )
    instant = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    clock = FixedClock(instant=instant)
    metrics = build_metrics("test_phase6_security")
    timer = DeterministicTimer()
    store_namespace = f"{namespace}:stores"
    rate_limit_store = InMemoryKeyValueStore(f"{store_namespace}:rl", clock)
    idempotency_store = InMemoryKeyValueStore(f"{store_namespace}:id", clock)
    old_signing = os.environ.get("DOWNLOAD_SIGNING_KEYS")
    old_tokens = os.environ.get("TOKENS")
    os.environ["DOWNLOAD_SIGNING_KEYS"] = json.dumps(
        [{"kid": "legacy", "secret": service_token, "state": "active"}], ensure_ascii=False
    )
    os.environ["TOKENS"] = json.dumps(
        [
            {"value": service_token, "role": "ADMIN"},
            {"value": metrics_token, "role": "METRICS_RO"},
        ],
        ensure_ascii=False,
    )
    try:
        app = create_application(
            config=config,
            clock=clock,
            metrics=metrics,
            timer=timer,
            rate_limit_store=rate_limit_store,
            idempotency_store=idempotency_store,
            readiness_probes={},
        )
        app.state.storage_root = tmp_path
        with TestClient(app) as client:
            yield client, app.state.metrics_collector
    finally:
        if old_signing is None:
            os.environ.pop("DOWNLOAD_SIGNING_KEYS", None)
        else:
            os.environ["DOWNLOAD_SIGNING_KEYS"] = old_signing
        if old_tokens is None:
            os.environ.pop("TOKENS", None)
        else:
            os.environ["TOKENS"] = old_tokens


def _invalid_params() -> dict[str, str]:
    signed_path = base64.urlsafe_b64encode("exports/sample.xlsx".encode("utf-8")).decode("utf-8").rstrip("=")
    future_expiry = 1704067200 + 600  # keep deterministic yet valid relative to fixture clock
    return {"signed": signed_path, "kid": "legacy", "exp": str(future_expiry), "sig": "invalid"}


def test_invalid_signature_triggers_block(download_security_client, retry_harness):
    client, collector = download_security_client
    runner, retry_metrics = retry_harness

    def _attempt():
        response = client.get("/download", params=_invalid_params())
        if response.status_code == 403:
            raise RuntimeError("forbidden")
        assert response.status_code == 429, get_debug_context(client.app, last_error=response.text)
        return response

    result, telemetry, _ = runner(_attempt, max_attempts=5, failure_threshold=6)
    assert result.status_code == 429
    assert telemetry.failures >= 4
    assert telemetry.attempts == 5

    blocked = client.get("/download", params=_invalid_params())
    payload = blocked.json()
    assert blocked.status_code == 429, get_debug_context(client.app, last_error=blocked.text)
    assert payload["fa_error_envelope"]["code"] == "DOWNLOAD_TEMPORARILY_BLOCKED", payload
    assert payload["fa_error_envelope"]["message"] == "دسترسی موقتاً مسدود شد.", payload

    snapshot = collector.snapshot()
    failure_reasons = {labels[0][1]: value for labels, value in snapshot["signature_failures"].items()}
    block_reasons = {labels[0][1]: value for labels, value in snapshot["signature_blocks"].items()}
    assert "signature" in failure_reasons, snapshot
    assert "signature" in block_reasons, snapshot

    retry_snapshot = retry_metrics.snapshot()
    retry_counts = {labels[0][1]: value for labels, value in retry_snapshot["retry_attempts"].items()}
    assert retry_counts.get("failure", 0) >= 4
    assert retry_counts.get("success", 0) >= 1


def test_get_debug_context_enriched():
    diagnostics = {
        "last_chain": ["rate_limit", "idempotency", "auth"],
        "last_rate_limit": {"decision": "allow"},
        "last_idempotency": {"status": "miss"},
        "last_auth": {"role": "ADMIN"},
    }

    class FakePool:
        def snapshot(self):
            return {"size": 1, "available": 1}

    class FakeCache(dict):
        def snapshot(self):
            return {"hit_rate": 0.95}

    app = SimpleNamespace(
        state=SimpleNamespace(
            diagnostics=diagnostics,
            connection_pool=FakePool(),
            cache_metrics=FakeCache({"hit_rate": 0.95}),
        )
    )
    context = get_debug_context(
        app,
        namespace="test-debug",
        last_error="error",
        redis_keys=["k1"],
    )
    assert "timestamp" in context
    assert "correlation_id" in context
    assert isinstance(context.get("memory_usage"), dict)
    assert context.get("middleware_order") == ["rate_limit", "idempotency", "auth"]
    assert context.get("active_connections") == {"size": 1, "available": 1}
    assert context.get("cache_hit_rate") == {"hit_rate": 0.95}
