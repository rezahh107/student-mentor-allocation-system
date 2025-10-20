"""Integration-aware tests enforcing middleware ordering guarantees."""

from __future__ import annotations

import random
import warnings
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
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
    """Run *func* with deterministic exponential backoff and jitter."""

    rng = random.Random(42)
    last_error: AssertionError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func(attempt)
        except AssertionError as exc:  # pragma: no cover - exercised on failure only
            last_error = exc
            delay = base_delay * (2 ** (attempt - 1)) + rng.uniform(0, base_delay / 4)
            time.sleep(delay)
    if last_error is None:  # defensive
        raise AssertionError("retry exhausted without assertion context")
    raise AssertionError(str(last_error)) from last_error


@pytest.fixture()
def deterministic_context() -> Dict[str, Any]:
    """Provide a deterministic factory context with unique namespaces and cleanup."""

    unique = uuid4().hex
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": f"import_to_sabt_test_{unique}"},
        database={"dsn": "postgresql+asyncpg://localhost/import_to_sabt_test"},
        auth={
            "metrics_token": f"metrics-token-{unique}",
            "service_token": f"service-token-{unique}",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )
    instant = datetime(2024, 1, 1, tzinfo=timezone.utc)
    clock = FixedClock(instant=instant)
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_test_{unique}")
    context = {
        "config": config,
        "clock": clock,
        "timer": timer,
        "metrics": metrics,
        "unique": unique,
        "service_token": f"service-token-{unique}",
    }
    yield context


def _assert_middleware_order(names: List[str], *, attempt: int) -> None:
    try:
        rate_idx = names.index("RateLimitMiddleware")
        idem_idx = names.index("IdempotencyMiddleware")
        auth_idx = names.index("AuthMiddleware")
    except ValueError as exc:
        raise AssertionError({"attempt": attempt, "missing": str(exc), "chain": names}) from exc
    assert rate_idx < idem_idx < auth_idx, {
        "attempt": attempt,
        "chain": names,
        "message": "Expected RateLimit → Idempotency → Auth order",
    }


def test_middleware_order_respected(deterministic_context: Dict[str, Any]) -> None:
    """Ensure RateLimit → Idempotency → Auth execution and declaration order."""

    def _build_and_verify(attempt: int) -> None:
        unique = deterministic_context["unique"]
        clock = deterministic_context["clock"]
        rate_store = InMemoryKeyValueStore(f"rate:{unique}:{attempt}", clock)
        idem_store = InMemoryKeyValueStore(f"idem:{unique}:{attempt}", clock)
        app = create_application(
            config=deterministic_context["config"],
            clock=clock,
            metrics=deterministic_context["metrics"],
            timer=deterministic_context["timer"],
            rate_limit_store=rate_store,
            idempotency_store=idem_store,
            readiness_probes={},
        )
        names = [middleware.cls.__name__ for middleware in app.user_middleware]
        _assert_middleware_order(names, attempt=attempt)
        with TestClient(app) as client:
            headers = {
                "Idempotency-Key": f"idempotency-{unique}-{attempt}",
                "X-Client-ID": f"client-{unique}",
                "Authorization": f"Bearer {deterministic_context['service_token']}",
            }
            response = client.post("/api/jobs", headers=headers, json={})
            payload = response.json()
            assert response.status_code == 200, {
                "attempt": attempt,
                "status": response.status_code,
                "payload": payload,
                "chain": names,
            }
            assert payload.get("middleware_chain") == [
                "RateLimit",
                "Idempotency",
                "Auth",
            ], {
                "attempt": attempt,
                "payload": payload,
                "chain": names,
            }
        rate_store._store.clear()
        idem_store._store.clear()

    _retry_with_backoff(_build_and_verify)
