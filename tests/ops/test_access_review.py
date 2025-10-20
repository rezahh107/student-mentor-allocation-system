from __future__ import annotations

import json
from datetime import datetime

import pytest

from sma.ops.audit_review import generate_access_review
from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome


@pytest.mark.asyncio
async def test_generates_report_and_updates_release_json(audit_env):
    service = audit_env.service
    clock = audit_env.clock
    clock.set(datetime(2024, 3, 15, 9, 30, tzinfo=clock.timezone))

    rid = "d58b7f8c-f8ec-4f41-9eaa-6e7286211111"
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope="north",
        action=AuditAction.AUTHN_OK,
        resource_type="auth",
        resource_id="signin",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )
    await service.record_event(
        actor_role=AuditActorRole.MANAGER,
        center_scope="north",
        action=AuditAction.UPLOAD_ACTIVATED,
        resource_type="upload",
        resource_id="batch",
        request_id="d58b7f8cf8ec4f419eaa6e728621aaaa",
        outcome=AuditOutcome.ERROR,
        error_code="VALIDATION_FAIL",
    )

    csv_path, json_path = await generate_access_review(service=service, manifest=audit_env.manifest)
    assert csv_path.exists() and json_path.exists(), audit_env.debug_context()

    csv_content = csv_path.read_text("utf-8")
    assert "north" in csv_content
    manifest = json.loads(audit_env.manifest.path.read_text("utf-8"))
    kinds = {entry["kind"] for entry in manifest["audit"]["artifacts"]}
    assert {"audit-review-csv", "audit-review-json"}.issubset(kinds), manifest
