from __future__ import annotations

import json
import os
from urllib.parse import unquote

import pytest

from tools.reqs_doctor.obs import JsonLogger


@pytest.fixture()
def metrics_token(monkeypatch):
    original = os.environ.get("METRICS_TOKEN")
    monkeypatch.setenv("METRICS_TOKEN", "token-secret-value")
    yield
    if original is None:
        monkeypatch.delenv("METRICS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("METRICS_TOKEN", original)


def test_redacts_env_tokens_and_query_params(metrics_token):
    payload = {
        "env": {"METRICS_TOKEN": "token-secret-value", "SAFE": "ok"},
        "url": "https://example.com/api?token=abc123&safe=yes",
        "authorization": "Bearer secretbearertokenvalue",
        "message": "token-secret-value seen",
    }

    sanitized = JsonLogger.redact(payload)

    assert sanitized["env"]["METRICS_TOKEN"] == "***REDACTED***"
    assert sanitized["env"]["SAFE"] == "ok"
    assert sanitized["url"].endswith("safe=yes")
    assert "***REDACTED***" in unquote(sanitized["url"])
    assert sanitized["authorization"].endswith("***REDACTED***")
    assert sanitized["message"] == "***REDACTED*** seen"

    serialized = JsonLogger.dumps(payload)
    data = json.loads(serialized)
    assert data["env"]["METRICS_TOKEN"] == "***REDACTED***"
