from __future__ import annotations

from collections import defaultdict
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


class FlakyStore(InMemoryKeyValueStore):
    def __init__(self, namespace: str, clock: FixedClock, fail_plan: Dict[str, int] | None = None) -> None:
        super().__init__(namespace, clock)
        self._plan = dict(fail_plan or {})
        self.failures = defaultdict(int)

    async def _maybe_fail(self, op: str) -> None:
        remaining = self._plan.get(op, 0)
        if remaining > 0:
            self._plan[op] = remaining - 1
            self.failures[op] += 1
            raise ConnectionError(f"transient-{op}")

    async def incr(self, key: str, ttl_seconds: int) -> int:  # type: ignore[override]
        await self._maybe_fail("incr")
        return await super().incr(key, ttl_seconds)

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:  # type: ignore[override]
        await self._maybe_fail("set_if_not_exists")
        return await super().set_if_not_exists(key, value, ttl_seconds)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:  # type: ignore[override]
        await self._maybe_fail("set")
        await super().set(key, value, ttl_seconds)


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
    timer = DeterministicTimer([0.0, 0.0, 0.0, 0.0])
    metrics = build_metrics(f"import_to_sabt_{unique}")
    return {"config": config, "clock": clock, "timer": timer, "metrics": metrics, "unique": unique}


def _assert_order(names: List[str]) -> None:
    rate_index = names.index("RateLimitMiddleware")
    idem_index = names.index("IdempotencyMiddleware")
    auth_index = names.index("AuthMiddleware")
    assert rate_index < idem_index < auth_index, {
        "chain": names,
        "rid": "middleware-order-retry",
        "message": "Expected RateLimit → Idempotency → Auth order",
    }


def test_post_order_with_retry_keeps_sequence() -> None:
    context = _build_context()
    unique = context["unique"]
    clock = context["clock"]
    rate_store = FlakyStore(f"rate:{unique}", clock, {"incr": 1})
    idem_store = FlakyStore(f"idem:{unique}", clock, {"set_if_not_exists": 1})
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
            "rid": "middleware-order-retry",
        }
        assert payload["middleware_chain"] == ["RateLimit", "Idempotency", "Auth"], payload
    assert rate_store.failures["incr"] == 1
    assert idem_store.failures["set_if_not_exists"] == 1
    rate_store._store.clear()
    idem_store._store.clear()
