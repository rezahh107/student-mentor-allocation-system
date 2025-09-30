from __future__ import annotations

import uuid
from typing import Sequence

import pytest

from tests.phase6_import_to_sabt.access_helpers import access_test_app


TOKENS: Sequence[dict[str, object]] = (
    {"value": "T" * 48, "role": "ADMIN"},
    {"value": "M" * 48, "role": "METRICS_RO"},
)

SIGNING_KEYS: Sequence[dict[str, object]] = (
    {"kid": "abcd", "secret": "S" * 64, "state": "active"},
)


def test_post_chain_order(
    monkeypatch: pytest.MonkeyPatch,
    metrics_registry_guard,
    redis_state_guard,
) -> None:
    metrics_namespace = redis_state_guard.namespace.replace(":", "-")
    with access_test_app(
        monkeypatch,
        tokens=TOKENS,
        signing_keys=SIGNING_KEYS,
        metrics_namespace=metrics_namespace,
        registry=metrics_registry_guard,
    ) as ctx:
        request_id = f"rid-{uuid.uuid4().hex}"
        headers = {
            "Authorization": f"Bearer {TOKENS[0]['value']}",
            "Idempotency-Key": redis_state_guard.key("jobs"),
            "X-Client-ID": redis_state_guard.namespace,
            "X-RateLimit-Key": redis_state_guard.namespace,
            "X-Request-ID": request_id,
        }
        payload = {"job": "import", "attempt": 1}
        response = ctx.client.post("/api/jobs", json=payload, headers=headers)
        rate_limit_samples = ctx.metrics.middleware.rate_limit_decision_total.collect()[0].samples
        idempotency_samples = ctx.metrics.middleware.idempotency_hits_total.collect()[0].samples
        debug = {
            "namespace": redis_state_guard.namespace,
            "redis": redis_state_guard.debug(),
            "headers": headers,
            "status": response.status_code,
            "metrics_samples": {
                "rate_limit": [sample.labels for sample in rate_limit_samples],
                "idempotency": [sample.labels for sample in idempotency_samples],
            },
        }
        assert response.status_code == 200, debug
        body = response.json()
        debug["body"] = body
        assert body["correlation_id"] == request_id, debug
        assert body["middleware_chain"] == ["RateLimit", "Idempotency", "Auth"], debug
        assert any(sample.labels.get("decision") == "allow" for sample in rate_limit_samples), debug
        assert any(sample.labels.get("outcome") == "miss" for sample in idempotency_samples), debug
