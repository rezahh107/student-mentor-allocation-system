from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 111},
]

SIGNING_KEYS = [
    {"kid": "KMID", "secret": "S" * 48, "state": "active"},
]


def test_order_is_rate_limit_then_idem_then_auth(monkeypatch) -> None:
    with access_test_app(monkeypatch, tokens=TOKENS, signing_keys=SIGNING_KEYS) as ctx:
        response = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": f"Bearer {TOKENS[0]['value']}",
                "Idempotency-Key": "idem-mw-order",
                "X-Client-ID": "order-client",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["middleware_chain"][:3] == ["rate_limit", "idempotency", "auth"]
