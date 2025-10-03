import uuid

import pytest

from src.hardened_api.middleware import RateLimitRule
from src.hardened_api.observability import get_metric
from tests.hardened_api.conftest import setup_test_data, temporary_rate_limit_config

pytest_plugins = ("pytest_asyncio.plugin", "tests.hardened_api.conftest")
pytestmark = [pytest.mark.asyncio]


async def test_exceed_limit_persian_error(client, clean_state):
    with temporary_rate_limit_config(client.app) as config:
        config.default_rule.requests = 1
        config.default_rule.window_seconds = 60
        config.per_route["/allocations"] = RateLimitRule(1, 60.0)

        suffix = f"{uuid.uuid4().int % 1_000_000:06d}"
        payload = setup_test_data(suffix)
        headers_first = {
            "Authorization": "Bearer TESTTOKEN1234567890",
            "Idempotency-Key": f"idem:limit:{uuid.uuid4().hex[:10]}",
            "Content-Type": "application/json; charset=utf-8",
        }

        first = await client.post("/allocations", json=payload, headers=headers_first)
        assert first.status_code == 200, first.text

        headers_second = dict(headers_first)
        headers_second["Idempotency-Key"] = f"idem:limit:{uuid.uuid4().hex[:10]}"

        second = await client.post("/allocations", json=payload, headers=headers_second)

    assert second.status_code == 429, second.text

    envelope = second.json()["error"]
    assert envelope["code"] == "RATE_LIMIT_EXCEEDED"
    assert envelope["message_fa"] == "تعداد درخواست‌ها از حد مجاز عبور کرده است؛ بعداً تلاش کنید."
    assert int(second.headers["Retry-After"]) >= 1

    metric = get_metric("rate_limit_events_total")
    limited = metric.labels(op="POST", endpoint="/allocations", outcome="limited", reason="quota_exceeded")._value.get()
    assert limited >= 1
