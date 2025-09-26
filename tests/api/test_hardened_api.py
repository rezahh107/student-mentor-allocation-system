from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from src.api.api import HardenedAPIConfig, create_app
from src.api.middleware import StaticCredential
from src.api.observability import iter_registry_metrics
from src.phase3_allocation import AllocationRequest, AllocationResult

VALID_STUDENT_ID = "0012345679"
VALID_MENTOR_ID = 128


@dataclass(slots=True)
class StubKeyInfo:
    consumer_id: str
    scopes: set[str]
    name: str | None = None
    expires_at: datetime | None = None
    is_active: bool = True


class StubAPIKeyProvider:
    def __init__(self, key: str, *, scopes: set[str]) -> None:
        self.key = key
        self.scopes = scopes

    async def verify(self, value: str) -> StubKeyInfo | None:
        if secrets.compare_digest(value, self.key):
            return StubKeyInfo(consumer_id="api:stub", scopes=self.scopes, name="stub")
        return None


class DummyAllocator:
    def __init__(self) -> None:
        self.calls: list[AllocationRequest] = []
        self.next_result: AllocationResult | None = None

    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        self.calls.append(request)
        if self.next_result is not None:
            result = self.next_result
            self.next_result = None
            return result
        key = f"idem-{request.student_id}-{request.mentor_id}"
        return AllocationResult(
            allocation_id=1,
            allocation_code="2300000001",
            year_code=request.year_code or "23",
            mentor_id=request.mentor_id,
            status="OK",
            message="عملیات موفق بود",
            error_code=None,
            idempotency_key=key,
            outbox_event_id="evt-1",
            dry_run=False,
        )


@pytest.fixture
def api_client() -> tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]:
    registry = CollectorRegistry()
    allocator = DummyAllocator()
    write_token = "ValidToken1234567890"
    read_token = "ReadToken1234567890"
    api_key_value = "ApiKeyToken1234567890"
    config = HardenedAPIConfig(
        allowed_origins=("https://portal.example",),
        max_body_bytes=32768,
        rate_limit_per_minute=2,
        rate_limit_burst=2,
        idempotency_ttl_seconds=3600,
        pii_salt="test-salt",
        static_tokens={
            write_token: StaticCredential(token=write_token, scopes=frozenset({"alloc:write", "alloc:read"}), consumer_id="token:write"),
            read_token: StaticCredential(token=read_token, scopes=frozenset({"alloc:read"}), consumer_id="token:read"),
        },
        jwt_secret="jwtsecretkey1234567890",
        leeway_seconds=120,
        metrics_token="metrics-secret",
        metrics_ip_allowlist={"127.0.0.1", "testclient"},
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )
    provider = StubAPIKeyProvider(api_key_value, scopes={"alloc:write", "alloc:read"})
    app = create_app(allocator, config=config, registry=registry, api_key_provider=provider)
    app.state.registry = registry
    app.state.allocator = allocator
    secrets_map = {
        "write_token": write_token,
        "read_token": read_token,
        "api_key": api_key_value,
    }
    return TestClient(app, raise_server_exceptions=False), allocator, registry, secrets_map


def _auth_headers(token: str, **extra: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
        "X-Request-ID": "req-123456789012",
    }
    headers.update(extra)
    return headers


def _base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "student_id": VALID_STUDENT_ID,
        "mentor_id": VALID_MENTOR_ID,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {"trace": "ok"},
        "metadata": {"source": "pytest"},
    }
    payload.update(overrides)
    return payload


def test_post_allocation_success(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, allocator, registry, secrets_map = api_client
    response = client.post("/allocations", headers=_auth_headers(secrets_map["write_token"]), json=_base_payload())
    assert response.status_code == 200
    data = response.json()
    assert data["allocationId"] == 1
    assert data["mentorId"] == VALID_MENTOR_ID
    assert data["status"] == "OK"
    assert "correlationId" in data
    assert allocator.calls, "allocator should have been invoked"
    samples = list(iter_registry_metrics(registry))
    assert any("http_requests_total" in sample for sample in samples)


def test_handles_persian_digits(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, allocator, _, secrets_map = api_client
    payload = _base_payload(student_id="۰۰۱۲۳۴۵۶۷۹", reg_center="۱", reg_status="۳", gender="۰")
    response = client.post("/allocations", headers=_auth_headers(secrets_map["write_token"]), json=payload)
    assert response.status_code == 200
    assert allocator.calls[-1].student_id == VALID_STUDENT_ID


def test_zero_width_student_id_rejected(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    payload = _base_payload(student_id="0‌012345679")
    response = client.post("/allocations", headers=_auth_headers(secrets_map["write_token"]), json=payload)
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body.get("details")
    assert any("student_id" in detail.get("loc", []) for detail in body["details"])


def test_missing_auth_returns_401(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, _ = api_client
    response = client.post("/allocations", headers={"Content-Type": "application/json; charset=utf-8"}, json=_base_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_invalid_token_returns_401(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, _ = api_client
    response = client.post("/allocations", headers=_auth_headers("badtokenbadtoken"), json=_base_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_scope_enforcement(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    response = client.post("/allocations", headers=_auth_headers(secrets_map["read_token"]), json=_base_payload())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_DENIED"


def test_api_key_authentication(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, allocator, _, secrets_map = api_client
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-API-Key": secrets_map["api_key"],
        "X-Request-ID": "req-223456789012",
    }
    response = client.post("/allocations", headers=headers, json=_base_payload())
    assert response.status_code == 200
    assert allocator.calls, "allocator should be invoked when API key is valid"


def test_rate_limiting_enforced(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    headers = _auth_headers(secrets_map["write_token"], **{"Idempotency-Key": "IdemToken12345678"})
    payload = _base_payload()
    client.post("/allocations", headers=headers, json=payload)
    client.post("/allocations", headers={**headers, "Idempotency-Key": "IdemToken12345679"}, json=payload)
    response = client.post("/allocations", headers={**headers, "Idempotency-Key": "IdemToken12345680"}, json=payload)
    assert response.status_code == 429
    assert response.headers.get("Retry-After") is not None
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_idempotency_replay(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, allocator, _, secrets_map = api_client
    headers = _auth_headers(secrets_map["write_token"], **{"Idempotency-Key": "IdempotencyKey1234"})
    payload = _base_payload()
    first = client.post("/allocations", headers=headers, json=payload)
    second = client.post("/allocations", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert len(allocator.calls) == 1
    assert first.json() == second.json()


def test_idempotency_conflict(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    headers = _auth_headers(secrets_map["write_token"], **{"Idempotency-Key": "IdempotencyKeyXYZ"})
    payload = _base_payload()
    client.post("/allocations", headers=headers, json=payload)
    conflict_payload = _base_payload(mentor_id=999)
    response = client.post("/allocations", headers=headers, json=conflict_payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_body_size_guard(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    bloated = _base_payload()
    bloated["extra"] = "x" * 40000
    response = client.post("/allocations", headers=_auth_headers(secrets_map["write_token"]), json=bloated)
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body.get("details")
    assert any(detail.get("type") == "value_error.body_size" for detail in body["details"])


def test_content_type_guard(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    headers = _auth_headers(secrets_map["write_token"])
    headers["Content-Type"] = "application/json"
    response = client.post("/allocations", headers=headers, json=_base_payload())
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(detail.get("loc") == ["header", "Content-Type"] for detail in body.get("details", []))


def test_metrics_requires_auth_or_allowlist(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    unauthorized = client.get("/metrics")
    assert unauthorized.status_code == 401
    token_allowed = client.get(
        "/metrics",
        headers={"Authorization": "Bearer metrics-secret"},
    )
    assert token_allowed.status_code == 200


def test_observability_logs_mask_pii(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    logger = logging.getLogger("student-allocation-api")
    captured: list[dict[str, object]] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            structured = getattr(record, "structured", None)
            if isinstance(structured, dict):
                captured.append(structured)

    handler = CaptureHandler()
    logger.addHandler(handler)
    headers = _auth_headers(secrets_map["write_token"], **{"Idempotency-Key": "IdempotencyKeyLog"})
    response = client.post("/allocations", headers=headers, json=_base_payload())
    assert response.status_code == 200
    logger.removeHandler(handler)
    assert captured, "expected structured logs"
    latest = captured[-1]
    assert latest["correlation_id"] == response.json()["correlationId"]
    assert "student_id" not in latest


def test_idempotent_replay_header(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, allocator, _, secrets_map = api_client
    headers = _auth_headers(secrets_map["write_token"], **{"Idempotency-Key": "ReplayKey12345678"})
    first = client.post("/allocations", headers=headers, json=_base_payload())
    assert first.status_code == 200
    calls_after_first = len(allocator.calls)
    second = client.post("/allocations", headers=headers, json=_base_payload())
    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert len(allocator.calls) == calls_after_first


def test_validation_errors_include_details(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    payload = _base_payload(gender=9)
    response = client.post("/allocations", headers=_auth_headers(secrets_map["write_token"]), json=payload)
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body.get("details")


def test_status_endpoint_requires_read_scope(api_client: tuple[TestClient, DummyAllocator, CollectorRegistry, dict[str, str]]) -> None:
    client, _, _, secrets_map = api_client
    response = client.get("/status", headers=_auth_headers(secrets_map["read_token"]))
    assert response.status_code == 200
    forbidden = client.get("/status", headers=_auth_headers("InvalidToken000000"))
    assert forbidden.status_code == 401
