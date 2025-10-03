"""Deterministic middleware order diagnostics regression tests."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics
if TYPE_CHECKING:  # pragma: no cover - typing only
    from tests.fixtures.state import CleanupFixtures

pytest_plugins = ["tests.fixtures.state"]


def _build_context(cleanup: "CleanupFixtures") -> Dict[str, object]:
    unique = f"diag-{uuid4().hex[:12]}"
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": f"import_to_sabt_{unique}"},
        database={"dsn": "postgresql://localhost/import_to_sabt"},
        auth={
            "metrics_token": f"metrics-{unique}",
            "service_token": f"service-{unique}",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_KEYS",
            "download_url_ttl_seconds": 900,
        },
        timezone="Asia/Tehran",
        enable_diagnostics=True,
    )
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_{unique}", registry=cleanup.registry)
    rate_store = InMemoryKeyValueStore(f"rate:{unique}", clock)
    idem_store = InMemoryKeyValueStore(f"idem:{unique}", clock)
    return {
        "config": config,
        "clock": clock,
        "timer": timer,
        "metrics": metrics,
        "rate_store": rate_store,
        "idem_store": idem_store,
        "unique": unique,
    }


def _assert_chain(names: List[str], context: Dict[str, object]) -> None:
    rate_index = names.index("RateLimitMiddleware")
    idem_index = names.index("IdempotencyMiddleware")
    auth_index = names.index("AuthMiddleware")
    assert rate_index < idem_index < auth_index, {
        "chain": names,
        "context": context,
        "message": "Expected RateLimit → Idempotency → Auth order",
    }


def test_middleware_chain_recorded_rate_limit_idem_auth(
    cleanup_fixtures: "CleanupFixtures",
) -> None:
    """Diagnostics capture the runtime middleware chain deterministically."""

    context = _build_context(cleanup_fixtures)
    app = create_application(
        config=context["config"],
        clock=context["clock"],
        metrics=context["metrics"],
        timer=context["timer"],
        rate_limit_store=context["rate_store"],
        idempotency_store=context["idem_store"],
        readiness_probes={},
    )
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    _assert_chain(names, context)

    headers = {
        "Idempotency-Key": f"idem-{cleanup_fixtures.namespace}",
        "X-Client-ID": "0client-123",
        "Authorization": f"Bearer service-{context['unique']}",
    }
    with TestClient(app) as client:
        response = client.post("/api/jobs", headers=headers, json={"size": "0"})
        payload = response.json()
        assert response.status_code == 200, cleanup_fixtures.context(response=response.text, payload=payload)
        assert payload["middleware_chain"] == ["RateLimit", "Idempotency", "Auth"], cleanup_fixtures.context(payload=payload)

    diagnostics = app.state.diagnostics
    assert diagnostics["last_chain"] == ["RateLimit", "Idempotency", "Auth"], cleanup_fixtures.context(diagnostics=diagnostics)

    decision_value = context["metrics"].registry.get_sample_value(
        f"import_to_sabt_{context['unique']}_rate_limit_decision_total",
        {"decision": "allow"},
    )
    idem_value = context["metrics"].registry.get_sample_value(
        f"import_to_sabt_{context['unique']}_idempotency_hits_total",
        {"outcome": "miss"},
    )
    assert decision_value == pytest.approx(1.0), cleanup_fixtures.context(decision=decision_value)
    assert idem_value == pytest.approx(1.0), cleanup_fixtures.context(idempotency=idem_value)

    context["rate_store"]._store.clear()  # type: ignore[attr-defined]
    context["idem_store"]._store.clear()  # type: ignore[attr-defined]
