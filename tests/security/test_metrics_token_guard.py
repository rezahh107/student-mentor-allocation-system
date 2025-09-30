from __future__ import annotations

import uuid

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 321},
    {"value": "C" * 32, "role": "METRICS_RO"},
]

SIGNING_KEYS = [
    {"kid": "ABCD", "secret": "S" * 48, "state": "active"},
]


def test_metrics_requires_token(monkeypatch, metrics_registry_guard, redis_state_guard) -> None:
    metrics_namespace = redis_state_guard.namespace.replace(":", "-")
    with access_test_app(
        monkeypatch,
        tokens=TOKENS,
        signing_keys=SIGNING_KEYS,
        metrics_namespace=metrics_namespace,
        registry=metrics_registry_guard,
    ) as ctx:
        missing = ctx.client.get(
            "/metrics",
            headers={"X-Request-ID": f"rid-{uuid.uuid4().hex}"},
        )
        missing_body = missing.json()
        debug_missing = {
            "status": missing.status_code,
            "body": missing_body,
            "failures": [sample.labels for sample in ctx.metrics.auth_fail_total.collect()[0].samples],
        }
        assert missing.status_code == 401, debug_missing
        assert missing_body["fa_error_envelope"]["code"] == "UNAUTHORIZED", debug_missing

        forbidden = ctx.client.get(
            "/metrics",
            headers={
                "Authorization": f"Bearer {TOKENS[0]['value']}",
                "X-Request-ID": f"rid-{uuid.uuid4().hex}",
            },
        )
        forbidden_body = forbidden.json()
        fail_samples = ctx.metrics.auth_fail_total.collect()[0].samples
        debug_forbidden = {
            "status": forbidden.status_code,
            "body": forbidden_body,
            "fail_samples": [sample.labels for sample in fail_samples],
        }
        assert forbidden.status_code == 403, debug_forbidden
        assert forbidden_body["fa_error_envelope"]["code"] == "METRICS_TOKEN_INVALID", debug_forbidden
        assert any(sample.labels["reason"] == "metrics_forbidden" for sample in fail_samples), debug_forbidden

        allowed = ctx.client.get(
            "/metrics",
            headers={
                "X-Metrics-Token": TOKENS[2]["value"],
                "X-Request-ID": f"rid-{uuid.uuid4().hex}",
            },
        )
        debug_allowed = {
            "status": allowed.status_code,
            "text": allowed.text[:128],
            "ok_samples": [sample.labels for sample in ctx.metrics.auth_ok_total.collect()[0].samples],
        }
        assert allowed.status_code == 200, debug_allowed
        ok_samples = ctx.metrics.auth_ok_total.collect()[0].samples
        assert any(sample.labels["role"] == "METRICS_RO" for sample in ok_samples), debug_allowed
