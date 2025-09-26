from __future__ import annotations

from typing import Callable

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from src.api.api import HardenedAPIConfig, create_app
from src.infrastructure.persistence.models import APIKeyModel, Base
from src.phase3_allocation import AllocationRequest, AllocationResult


class NoopAllocator:
    def __init__(self) -> None:
        self.calls: list[AllocationRequest] = []

    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        self.calls.append(request)
        return AllocationResult(
            allocation_id=1,
            allocation_code="2301",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message="",
            error_code=None,
            idempotency_key="k",
            outbox_event_id="evt",
            dry_run=False,
        )


@pytest.fixture()
def admin_client() -> tuple[TestClient, Callable[[], Session], str]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    def session_factory() -> Session:
        return SessionLocal()

    allocator = NoopAllocator()
    registry = CollectorRegistry()
    admin_token = "admin-secret-token"
    config = HardenedAPIConfig(
        allowed_origins=("https://portal.example",),
        static_tokens={},
        jwt_secret="jwtsecretkey1234567890",
        admin_token=admin_token,
        metrics_token=admin_token,
        metrics_ip_allowlist={"127.0.0.1", "testclient"},
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )
    app = create_app(
        allocator,
        config=config,
        registry=registry,
        session_factory=session_factory,
    )
    return TestClient(app, raise_server_exceptions=False), session_factory, admin_token


def test_admin_requires_token(admin_client) -> None:
    client, _, _ = admin_client
    response = client.get("/admin")
    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "AUTH_REQUIRED"


def test_dashboard_renders_with_csp(admin_client) -> None:
    client, _, token = admin_client
    response = client.get("/admin", headers={"X-Admin-Token": token})
    assert response.status_code == 200
    assert 'dir="rtl"' in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in csp
    assert "style-src 'self' 'nonce-" in csp
    assert "nonce=" in response.text


def test_admin_key_lifecycle(admin_client) -> None:
    client, session_factory, token = admin_client
    create = client.post(
        "/admin/api-keys",
        headers={"X-Admin-Token": token, "Content-Type": "application/json; charset=utf-8"},
        json={"name": "ops", "scopes": ["alloc:read"]},
    )
    assert create.status_code == 200
    data = create.json()
    assert data["message_fa"].startswith("کلید")
    value = data["value"]
    assert len(value) >= 16
    key_id = data["key"]["id"]

    rotate = client.post(
        f"/admin/api-keys/{key_id}/rotate",
        headers={"X-Admin-Token": token, "Content-Type": "application/json; charset=utf-8"},
        json={"hint": "rotation"},
    )
    assert rotate.status_code == 200
    rotated_value = rotate.json()["value"]
    assert rotated_value != value

    disable = client.post(
        f"/admin/api-keys/{key_id}/disable",
        headers={"X-Admin-Token": token},
    )
    assert disable.status_code == 200
    with session_factory() as session:
        record = session.get(APIKeyModel, key_id)
        assert record is not None
        assert record.disabled_at is not None


def test_admin_metrics_view(admin_client) -> None:
    client, _, token = admin_client
    metrics = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


def test_diagnostics_payload(admin_client) -> None:
    client, _, token = admin_client
    response = client.get("/admin/diagnostics", headers={"X-Admin-Token": token})
    assert response.status_code == 200
    data = response.json()
    assert data["message_fa"].startswith("گزارش سلامت")
    assert isinstance(data["rate_limits"], dict)
    assert isinstance(data["idempotency"], dict)
    assert "correlation_id" in data
