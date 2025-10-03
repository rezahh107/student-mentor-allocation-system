import asyncio
import uuid
from typing import Any, Tuple

import pytest

from src.hardened_api.middleware import RateLimitRule
from src.hardened_api.observability import get_metric
from src.hardened_api.redis_support import RateLimitResult
from tests.hardened_api.conftest import setup_test_data, temporary_rate_limit_config

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_only_one_succeeds(client, clean_state):
    with temporary_rate_limit_config(client.app) as config:
        config.default_rule.requests = 1000
        config.default_rule.window_seconds = 60
        config.per_route["/allocations"] = RateLimitRule(1000, 60.0)

    class _BypassLimiter:
        async def allow(self, *args, **kwargs) -> RateLimitResult:  # pragma: no cover - simple stub
            requests = kwargs.get("requests", 1000)
            return RateLimitResult(allowed=True, remaining=requests)

    limiter = client.app.state.middleware_state.rate_limiter
    client.app.state.middleware_state.rate_limiter = _BypassLimiter()

    idem_key = f"idem:batch:{uuid.uuid4().hex[:16]}"
    suffix = f"{uuid.uuid4().int % 1_000_000:06d}"
    payload = setup_test_data(suffix)
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Idempotency-Key": idem_key,
        "Content-Type": "application/json; charset=utf-8",
    }

    async def fire_request() -> Tuple[int, dict[str, Any]]:
        local_headers = dict(headers)
        local_headers["X-API-Key"] = "STATICKEY1234567890"
        response = await client.post("/allocations", json=payload, headers=local_headers)
        body = response.json()
        return response.status_code, body

    try:
        results = await asyncio.gather(*(fire_request() for _ in range(50)))
    finally:
        client.app.state.middleware_state.rate_limiter = limiter

    successes = [body for status, body in results if status == 200]
    conflicts = [body for status, body in results if status == 409]

    assert len(successes) == 1, results
    assert len(conflicts) == 49, [status for status, _ in results]
    for body in conflicts:
        envelope = body.get("error", {})
        assert envelope.get("code") == "IDEMPOTENT_REPLAY", body
        assert (
            envelope.get("message_fa")
            == "این درخواست قبلاً پردازش شده است؛ از کلید تکرارناپذیر جدید استفاده کنید."
        ), body
        assert envelope.get("correlation_id"), body

    idempotency_metric = get_metric("idempotency_events_total")
    replay_total = idempotency_metric.labels(op="POST", endpoint="/allocations", outcome="replay", reason="completed")._value.get()
    assert replay_total >= 1
