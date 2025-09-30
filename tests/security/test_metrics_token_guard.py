from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 321},
    {"value": "C" * 32, "role": "METRICS_RO"},
]

SIGNING_KEYS = [
    {"kid": "ABCD", "secret": "S" * 48, "state": "active"},
]


def test_metrics_requires_token(monkeypatch) -> None:
    with access_test_app(monkeypatch, tokens=TOKENS, signing_keys=SIGNING_KEYS) as ctx:
        forbidden = ctx.client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {TOKENS[0]['value']}"},
        )
        assert forbidden.status_code == 403
        body = forbidden.json()
        assert body["fa_error_envelope"]["code"] == "METRICS_TOKEN_INVALID"

        fail_samples = ctx.metrics.auth_fail_total.collect()[0].samples
        assert any(sample.labels["reason"] == "metrics_forbidden" for sample in fail_samples)

        allowed = ctx.client.get(
            "/metrics",
            headers={"Authorization": f"Bearer {TOKENS[2]['value']}"},
        )
        assert allowed.status_code == 200
        ok_samples = ctx.metrics.auth_ok_total.collect()[0].samples
        assert any(sample.labels["role"] == "METRICS_RO" for sample in ok_samples)
