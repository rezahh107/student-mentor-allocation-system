from __future__ import annotations

from tests.phase6_import_to_sabt.access_helpers import access_test_app

TOKENS = [
    {"value": "A" * 32, "role": "ADMIN"},
    {"value": "B" * 32, "role": "MANAGER", "center": 404},
    {"value": "C" * 32, "role": "METRICS_RO"},
]

SIGNING_KEYS = [
    {"kid": "KEYZ", "secret": "S" * 48, "state": "active"},
]


def test_auth_logs_masked(monkeypatch, capsys) -> None:
    with access_test_app(monkeypatch, tokens=TOKENS, signing_keys=SIGNING_KEYS) as ctx:
        capsys.readouterr()
        response = ctx.client.post(
            "/api/jobs",
            headers={
                "Authorization": f"Bearer {TOKENS[0]['value']}",
                "Idempotency-Key": "idem-1234567890abcd",
                "X-Client-ID": "log-client",
            },
        )
        assert response.status_code == 200

        stdout = capsys.readouterr().out
        assert "auth.ok" in stdout
        assert TOKENS[0]["value"] not in stdout
        assert "fingerprint" in stdout
