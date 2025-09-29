from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 707},
]

SIGNING_KEYS = [
    {"kid": "AKEY", "secret": "S" * 48, "state": "active"},
]


def test_authn_ok_fail(monkeypatch, capsys) -> None:
    with access_test_app(monkeypatch, tokens=TOKENS, signing_keys=SIGNING_KEYS) as ctx:
        capsys.readouterr()
        unauthorized = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": "Bearer invalid-token-value",  # guaranteed miss
                "Idempotency-Key": "idem-failure-case-001",
                "X-Client-ID": "audit-client",
            },
        )
        assert unauthorized.status_code == 401
        stdout = capsys.readouterr().out
        assert "auth.failed" in stdout
        assert "unknown_token" in stdout

        ok = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": f"Bearer {TOKENS[0]['value']}",
                "Idempotency-Key": "idem-success-case-002",
                "X-Client-ID": "audit-client",
            },
        )
        assert ok.status_code == 200
        success_out = capsys.readouterr().out
        assert "auth.ok" in success_out
        assert "fingerprint" in success_out
