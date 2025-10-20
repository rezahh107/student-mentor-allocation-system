from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging

from sma.core.retry import retry_attempts_total, retry_backoff_seconds, retry_exhaustion_total

from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application
from tests.mw.test_order_retry import FlakyStore, _build_context


def test_parallel_posts_single_commit(caplog) -> None:
    caplog.set_level(logging.INFO)
    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()
    context = _build_context()
    unique = context["unique"]
    clock = context["clock"]
    rate_store = FlakyStore(f"rate:{unique}", clock, {"incr": 1})
    idem_store = FlakyStore(f"idem:{unique}", clock, {"set_if_not_exists": 1, "set": 1})
    app = create_application(
        config=context["config"],
        clock=clock,
        metrics=context["metrics"],
        timer=context["timer"],
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    headers = {
        "Idempotency-Key": f"idem-{unique}",
        "X-Client-ID": f"client-{unique}",
        "Authorization": f"Bearer service-{unique}",
    }
    with TestClient(app) as client:
        def _issue() -> tuple[int, dict[str, object]]:
            response = client.post("/api/jobs", headers=headers, json={})
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text}
            return response.status_code, payload

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _issue(), range(2)))

        follow_up_status, follow_up_payload = _issue()

    statuses = [status for status, _ in results]
    payloads = [payload for _, payload in results]
    success_payloads = [payload for status, payload in results if status == 200]
    assert statuses.count(200) <= 1, {
        "statuses": statuses,
        "payloads": payloads,
        "rid": "concurrent-idem",
        "message": "At most one immediate POST should succeed",
    }
    assert follow_up_status == 200, {
        "follow_up_status": follow_up_status,
        "follow_up_payload": follow_up_payload,
        "rid": "concurrent-idem",
    }
    for payload in success_payloads + [follow_up_payload]:
        assert payload.get("middleware_chain") == ["RateLimit", "Idempotency", "Auth"], {
            "payload": payload,
            "rid": "concurrent-idem",
        }
    assert follow_up_payload.get("processed") is True, {
        "follow_up_payload": follow_up_payload,
        "rid": "concurrent-idem",
        "message": "Follow-up POST should return processed confirmation",
    }
    assert rate_store.failures["incr"] == 1
    assert idem_store.failures["set_if_not_exists"] == 1
    assert idem_store.failures["set"] == 1
    metrics_ops = {
        sample.labels.get("op")
        for metric in retry_attempts_total.collect()
        for sample in metric.samples
        if sample.value
    }
    assert {"ratelimit.incr", "idempotency.set_if_not_exists", "idempotency.set"}.issubset(metrics_ops)
    histogram_ops = {
        sample.labels.get("op")
        for metric in retry_backoff_seconds.collect()
        for sample in metric.samples
        if sample.value
    }
    assert histogram_ops, "retry histogram must record deterministic backoff"
    assert unique not in caplog.text
    retry_attempts_total.clear()
    retry_backoff_seconds.clear()
    retry_exhaustion_total.clear()
    rate_store._store.clear()
    idem_store._store.clear()
