from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.audit.api import create_audit_api
from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.service import build_metrics


class _DummyService:
    def __init__(self) -> None:
        self._tz = ZoneInfo("Asia/Tehran")
        self._registry = CollectorRegistry()
        self._metrics = build_metrics(registry=self._registry)

    def now(self) -> datetime:
        return datetime(2024, 3, 1, 8, 0, tzinfo=self._tz)

    @property
    def timezone(self) -> ZoneInfo:
        return self._tz

    @property
    def metrics_registry(self) -> CollectorRegistry:
        return self._metrics.registry

    async def list_events(self, query: Any):  # pragma: no cover - deterministic stub
        return []

    async def get_event(self, event_id: int):  # pragma: no cover
        return None

    async def record_event(
        self,
        *,
        actor_role: AuditActorRole,
        center_scope: str | None,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        request_id: str,
        outcome: AuditOutcome,
        job_id: str | None = None,
        error_code: str | None = None,
        artifact_sha256: str | None = None,
    ) -> int:  # pragma: no cover - deterministic stub
        return 1


class _DummyExporter:
    async def export(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError


def test_order_is_ratelimit_idem_auth() -> None:
    service = _DummyService()
    exporter = _DummyExporter()
    app = create_audit_api(service=service, exporter=exporter, metrics_token="tok")
    transport = httpx.ASGITransport(app=app)

    async def _call() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(
                "/audit",
                headers={"X-Correlation-ID": "rid-123", "X-Role": "ADMIN", "Authorization": "Bearer test"},
            )

    response = asyncio.run(_call())
    assert response.status_code == 200
    order_header = response.headers.get("X-Middleware-Order")
    assert order_header == "RateLimit,Idempotency,Auth"
