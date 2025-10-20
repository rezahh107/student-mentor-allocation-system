from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4

from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics


def _build_context() -> Dict[str, object]:
    unique = uuid4().hex
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
    )
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_{unique}")
    return {"config": config, "clock": clock, "timer": timer, "metrics": metrics, "unique": unique}


def _assert_order(names: List[str]) -> None:
    rate_index = names.index("RateLimitMiddleware")
    idem_index = names.index("IdempotencyMiddleware")
    auth_index = names.index("AuthMiddleware")
    assert rate_index < idem_index < auth_index, {
        "chain": names,
        "rid": "middleware-order",
        "message": "Expected RateLimit → Idempotency → Auth order",
    }


def test_middleware_order_respected_post_exports() -> None:
    context = _build_context()
    unique = context["unique"]
    clock = context["clock"]
    rate_store = InMemoryKeyValueStore(f"rate:{unique}", clock)
    idem_store = InMemoryKeyValueStore(f"idem:{unique}", clock)
    app = create_application(
        config=context["config"],
        clock=clock,
        metrics=context["metrics"],
        timer=context["timer"],
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    _assert_order(names)
    headers = {
        "Idempotency-Key": f"idem-{unique}",
        "X-Client-ID": f"client-{unique}",
        "Authorization": f"Bearer service-{unique}",
    }
    with TestClient(app) as client:
        response = client.post("/api/jobs", headers=headers, json={})
        payload = response.json()
        assert response.status_code == 200, {
            "status": response.status_code,
            "payload": payload,
            "rid": "middleware-order",
        }
        assert payload["middleware_chain"] == ["RateLimit", "Idempotency", "Auth"], {
            "payload": payload,
            "rid": "middleware-order",
        }
    rate_store._store.clear()
    idem_store._store.clear()

