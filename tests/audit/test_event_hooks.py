from __future__ import annotations

import pytest

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.repository import AuditQuery


@pytest.mark.asyncio
async def test_export_finalized_emits_event(audit_env):
    rid = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    service = audit_env.service
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope="center-۱",
        action=AuditAction.UPLOAD_CREATED,
        resource_type="upload",
        resource_id="batch-01",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )

    query = AuditQuery(limit=None)
    export_result = await audit_env.exporter.export(
        fmt="csv",
        query=query,
        bom=False,
        rid=rid,
        actor_role=AuditActorRole.ADMIN,
        center_scope="center-۱",
    )

    events = await service.list_events(AuditQuery(action=AuditAction.EXPORT_FINALIZED, limit=5))
    assert any(event.artifact_sha256 == export_result.sha256 for event in events), audit_env.debug_context()
    assert export_result.path.exists(), audit_env.debug_context()
