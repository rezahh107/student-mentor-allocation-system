"""Ensure the /metrics endpoint remains token-guarded with deterministic state."""

from __future__ import annotations

import random
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics

warnings.filterwarnings(
    "ignore",
    message="The 'app' shortcut is now deprecated",
    category=DeprecationWarning,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:The 'app' shortcut is now deprecated:DeprecationWarning"
)


def _retry_with_backoff(func, *, attempts: int = 3, base_delay: float = 0.02) -> Any:
    rng = random.Random(17)
    last_error: AssertionError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func(attempt)
        except AssertionError as exc:  # pragma: no cover - exercised on failure only
            last_error = exc
            jitter = rng.uniform(0, base_delay / 3)
            time.sleep(base_delay * (2 ** (attempt - 1)) + jitter)
    if last_error is None:
        raise AssertionError("retry exhausted without assertion context")
    raise AssertionError(str(last_error)) from last_error


@pytest.fixture()
def metrics_app() -> Dict[str, Any]:
    unique = uuid4().hex
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": f"import_to_sabt_metrics_{unique}"},
        database={"dsn": "postgresql+asyncpg://localhost/import_to_sabt_metrics"},
        auth={
            "metrics_token": f"metrics-token-{unique}",
            "service_token": f"service-token-{unique}",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )
    clock = FixedClock(instant=datetime(2024, 1, 1, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_metrics_{unique}")
    rate_store = InMemoryKeyValueStore(f"rate:{unique}", clock)
    idem_store = InMemoryKeyValueStore(f"idem:{unique}", clock)
    rate_store._store.clear()
    idem_store._store.clear()
    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    context = {
        "app": app,
        "metrics_token": f"metrics-token-{unique}",
        "rate_store": rate_store,
        "idem_store": idem_store,
    }
    yield context
    rate_store._store.clear()
    idem_store._store.clear()


def test_metrics_endpoint_requires_valid_token(metrics_app: Dict[str, Any]) -> None:
    """/metrics must reject anonymous calls and honour the read-only token."""

    app = metrics_app["app"]

    def _call_without_token(attempt: int) -> int:
        with TestClient(app) as client:
            response = client.get("/metrics")
            assert response.status_code in {401, 403}, {
                "attempt": attempt,
                "status": response.status_code,
                "body": response.json(),
            }
            return response.status_code

    unauthorised_status = _retry_with_backoff(_call_without_token)
    assert unauthorised_status in {401, 403}

    def _call_with_token(attempt: int) -> str:
        headers = {"X-Metrics-Token": metrics_app["metrics_token"]}
        with TestClient(app) as client:
            response = client.get("/metrics", headers=headers)
            body = response.text
            assert response.status_code == 200, {
                "attempt": attempt,
                "status": response.status_code,
                "body": body,
                "headers": dict(response.headers),
            }
            assert body.startswith("# HELP") or "_metrics" in body, {
                "attempt": attempt,
                "body": body[:200],
            }
            return body

    metrics_payload = _retry_with_backoff(_call_with_token)
    assert "# HELP" in metrics_payload or "_total" in metrics_payload
