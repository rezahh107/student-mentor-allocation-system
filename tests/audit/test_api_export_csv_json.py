from __future__ import annotations

import codecs
import csv
import io
import json

import pytest
from httpx import ASGITransport, AsyncClient

from src.audit.api import Principal, create_audit_api, get_principal
from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome


@pytest.mark.asyncio
async def test_csv_excel_safety_crlf_bom(audit_env):
    service = audit_env.service
    rid = "15f5a9e7-0000-4edb-bb95-4c7b2b5f8f44"
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope="مرکز",
        action=AuditAction.AUTHN_OK,
        resource_type="signin",
        resource_id="=SUM(A1:A2)",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope="مرکز",
        action=AuditAction.AUTHN_FAIL,
        resource_type="signin",
        resource_id="+Hidden",
        request_id="e2d532fbd5b4439b8f8640a1d7c56154",
        outcome=AuditOutcome.ERROR,
        error_code="AUTH_FAIL",
    )

    app = create_audit_api(service=service, exporter=audit_env.exporter, secret_key="secret۹۹۹")
    app.dependency_overrides[get_principal] = lambda: Principal(role=AuditActorRole.ADMIN, center_scope="مرکز")
    token = app.state.audit_signer.sign("/audit/export:ADMIN:مرکز")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit/export",
            params={"format": "csv", "bom": "true", "token": token},
        )
        body = await response.aread()

    assert response.status_code == 200, audit_env.debug_context()
    assert body.startswith(codecs.BOM_UTF8), "CSV باید با BOM شروع شود"
    decoded = body.decode("utf-8-sig")
    assert "\r\n" in decoded, decoded
    reader = csv.reader(io.StringIO(decoded))
    rows = list(reader)
    assert rows[1][5].startswith("'"), rows
    assert rows[2][5].startswith("'"), rows
    assert response.headers["Content-Disposition"].startswith("attachment"), response.headers

    manifest = json.loads(audit_env.manifest.path.read_text("utf-8"))
    assert any(entry["kind"] == "audit-export-csv" for entry in manifest["audit"]["artifacts"]), manifest


@pytest.mark.asyncio
async def test_json_export_stream(audit_env):
    service = audit_env.service
    rid = "0d73d0f5-8f86-4f2a-9bd9-6a3d3d2f9f11"
    await service.record_event(
        actor_role=AuditActorRole.MANAGER,
        center_scope="A",
        action=AuditAction.UPLOAD_ACTIVATED,
        resource_type="upload",
        resource_id="batch",
        request_id=rid,
        outcome=AuditOutcome.OK,
    )

    app = create_audit_api(service=service, exporter=audit_env.exporter, secret_key="secret۹۹۹")
    app.dependency_overrides[get_principal] = lambda: Principal(role=AuditActorRole.MANAGER, center_scope="A")
    token = app.state.audit_signer.sign("/audit/export:MANAGER:A")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/audit/export",
            params={"format": "json", "bom": "false", "token": token},
        )
        body = await response.aread()

    assert response.status_code == 200, audit_env.debug_context()
    assert not body.startswith(codecs.BOM_UTF8)
    data = json.loads(body.decode("utf-8"))
    assert data[0]["action"] == "UPLOAD_ACTIVATED"
    manifest = json.loads(audit_env.manifest.path.read_text("utf-8"))
    assert any(entry["kind"] == "audit-export-json" for entry in manifest["audit"]["artifacts"]), manifest
