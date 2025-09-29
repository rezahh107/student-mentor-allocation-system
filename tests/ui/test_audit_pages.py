from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.audit.api import Principal, create_audit_api, get_principal
from src.audit.enums import AuditAction, AuditActorRole, AuditOutcome


@pytest.mark.asyncio
async def test_rtl_filters_htmx(audit_env):
    service = audit_env.service
    await service.record_event(
        actor_role=AuditActorRole.ADMIN,
        center_scope=None,
        action=AuditAction.AUTHN_OK,
        resource_type="auth",
        resource_id="signin",
        request_id="5e0d4dcd-dc03-4f31-8b4c-2c1cd2d72b44",
        outcome=AuditOutcome.OK,
    )

    app = create_audit_api(service=service, exporter=audit_env.exporter, secret_key="secret۹۹۹")
    app.dependency_overrides[get_principal] = lambda: Principal(role=AuditActorRole.ADMIN, center_scope=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ui/audit")

    html = response.text
    assert "dir=\"rtl\"" in html
    assert "hx-get=\"/audit\"" in html
    assert "اعمال فیلتر" in html
    assert "لینک دانلود" in html

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        exports_page = await client.get("/ui/audit/exports")
    assert "امضاشده" in exports_page.text or "امضا" in exports_page.text
