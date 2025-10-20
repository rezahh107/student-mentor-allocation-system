from __future__ import annotations

import asyncio
import pytest
from sqlalchemy import text

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.repository import AuditQuery


@pytest.mark.asyncio
async def test_insert_only_trigger(audit_env):
    service = audit_env.service
    rid = "123e4567-e89b-12d3-a456-426614174000"
    event_id = await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope=None,
        action=AuditAction.AUTHN_OK,
        resource_type="auth",
        resource_id="login",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )

    async def run(statement, params):
        def _run():
            with audit_env.engine.begin() as conn:
                conn.execute(statement, params)
        await asyncio.to_thread(_run)

    with pytest.raises(Exception) as update_error:
        await run(text("UPDATE audit_events SET action='AUTHN_FAIL' WHERE id=:id"), {"id": event_id})
    assert "AUDIT_APPEND_ONLY" in str(update_error.value), audit_env.debug_context()

    with pytest.raises(Exception) as delete_error:
        await run(text("DELETE FROM audit_events WHERE id=:id"), {"id": event_id})
    assert "AUDIT_APPEND_ONLY" in str(delete_error.value), audit_env.debug_context()

    events = await service.list_events(AuditQuery(limit=10))
    assert any(event.id == event_id for event in events), audit_env.debug_context()
