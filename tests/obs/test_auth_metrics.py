from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 909},
]

SIGNING_KEYS = [
    {"kid": "KOBS", "secret": "S" * 48, "state": "active"},
]


def test_counters_increment(monkeypatch) -> None:
    with access_test_app(monkeypatch, tokens=TOKENS, signing_keys=SIGNING_KEYS) as ctx:
        denied = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": "Bearer bad-token",  # ensures failure path
                "Idempotency-Key": "idem-metrics-fail",
                "X-Client-ID": "metrics-client",
            },
        )
        assert denied.status_code == 401

        allowed = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": f"Bearer {TOKENS[0]['value']}",
                "Idempotency-Key": "idem-metrics-ok",
                "X-Client-ID": "metrics-client",
            },
        )
        assert allowed.status_code == 200

        fail_samples = ctx.metrics.auth_fail_total.collect()[0].samples
        assert any(sample.labels["reason"] == "unknown_token" for sample in fail_samples)
        ok_samples = ctx.metrics.auth_ok_total.collect()[0].samples
        assert any(sample.labels["role"] == "ADMIN" for sample in ok_samples)
