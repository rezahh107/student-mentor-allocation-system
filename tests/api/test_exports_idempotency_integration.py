"""Integration tests for exports idempotency enforcement."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.filterwarnings("error")

HAS_APP = False
try:
    try:
        from src.main import app  # type: ignore
    except Exception:  # pragma: no cover
        from main import app  # type: ignore
    from fastapi.testclient import TestClient

    client = TestClient(app)
    HAS_APP = True
except Exception:  # pragma: no cover
    client = None


@pytest.mark.skipif(not HAS_APP, reason="app not importable")
def test_exports_post_without_idempotency_key_returns_400() -> None:
    headers = {
        "Authorization": f"Bearer {os.getenv('IMPORT_TO_SABT_AUTH__SERVICE_TOKEN', 'dev-admin')}",
        "X-Role": "ADMIN",
    }
    payload = {"year": 1402}
    response = client.post("/api/exports?format=csv", headers=headers, json=payload)
    assert response.status_code == 400
    body = response.json()
    if isinstance(body, dict):
        if "detail" in body and isinstance(body["detail"], dict):
            body = body["detail"]
        if "fa_error_envelope" in body and isinstance(body["fa_error_envelope"], dict):
            body = body["fa_error_envelope"]
    assert body.get("code") == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.skipif(not HAS_APP, reason="app not importable")
def test_exports_post_with_idempotency_key_succeeds() -> None:
    headers = {
        "Authorization": f"Bearer {os.getenv('IMPORT_TO_SABT_AUTH__SERVICE_TOKEN', 'dev-admin')}",
        "Idempotency-Key": "test-integration-123",
        "X-Role": "ADMIN",
    }
    payload = {"year": 1402}
    response = client.post("/api/exports?format=csv", headers=headers, json=payload)
    assert response.status_code in (200, 201, 202)
