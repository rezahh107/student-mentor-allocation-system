from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from src.api.api import HardenedAPIConfig, create_app
from src.phase3_allocation import AllocationRequest, AllocationResult


class SilentAllocator:
    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        return AllocationResult(
            allocation_id=1,
            allocation_code="23",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message="",
            error_code=None,
            idempotency_key="id",
            outbox_event_id="evt",
            dry_run=False,
        )


def _encode_jwt(payload: dict[str, object], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    segments = []
    for obj in (header, payload):
        segment = base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode("utf-8")).rstrip(b"=")
        segments.append(segment)
    signing_input = b".".join(segments)
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(base64.urlsafe_b64encode(signature).rstrip(b"="))
    return b".".join(segments).decode("ascii")


@pytest.fixture()
def secured_app() -> TestClient:
    allocator = SilentAllocator()
    registry = CollectorRegistry()
    config = HardenedAPIConfig(
        metrics_token="metrics-token",
        metrics_ip_allowlist={"192.0.2.1"},
        jwt_secret="secret",
        jwt_issuer="alloc",
        jwt_audience="student",
        static_tokens={},
        required_scopes={"/status": {"alloc:read"}},
    )
    app = create_app(allocator, config=config, registry=registry)
    return TestClient(app, raise_server_exceptions=False)


def test_metrics_requires_token(secured_app: TestClient) -> None:
    response = secured_app.get("/metrics")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_metrics_wrong_ip_forbidden(secured_app: TestClient) -> None:
    response = secured_app.get("/metrics", headers={"Authorization": "Bearer metrics-token"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_DENIED"


def test_jwt_issuer_and_audience_validation(secured_app: TestClient) -> None:
    now = int(time.time())
    good_payload = {"iss": "alloc", "aud": "student", "exp": now + 300, "iat": now, "sub": "svc", "scopes": "alloc:read"}
    bad_payload = {**good_payload, "iss": "other"}
    good = _encode_jwt(good_payload, "secret")
    bad = _encode_jwt(bad_payload, "secret")

    good_response = secured_app.get(
        "/status",
        headers={"Authorization": f"Bearer {good}"},
    )
    assert good_response.status_code == 200

    bad_response = secured_app.get(
        "/status",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert bad_response.status_code == 401
    assert bad_response.json()["error"]["code"] == "INVALID_TOKEN"
