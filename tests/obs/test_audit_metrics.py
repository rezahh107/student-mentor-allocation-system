from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from src.audit.repository import AuditQuery


@pytest.mark.asyncio
async def test_counters_labels(audit_env):
    registry: CollectorRegistry = audit_env.registry
    service = audit_env.service

    rid = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope=None,
        action=AuditAction.AUTHN_OK,
        resource_type="auth",
        resource_id="signin",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )

    await audit_env.exporter.export(
        fmt="json",
        query=AuditQuery(limit=None),
        bom=False,
        rid=rid,
        actor_role=AuditActorRole.ADMIN,
        center_scope=None,
    )
    service.record_review_run("ok")

    metrics_blob = generate_latest(registry).decode("utf-8")
    assert "audit_events_total" in metrics_blob
    assert "audit_export_bytes_total" in metrics_blob
    assert "audit_review_runs_total" in metrics_blob
