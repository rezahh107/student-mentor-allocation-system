from __future__ import annotations

import pytest

from sma.audit.enums import AuditAction, AuditActorRole
from sma.audit.hooks import audited_config_parse
from sma.audit.repository import AuditQuery
from sma.phase7_release.config_guard import ConfigGuard, ConfigValidationError


@pytest.mark.asyncio
async def test_config_rejected_emits_event(audit_env):
    guard = ConfigGuard(env={"METRICS_TOKEN": "metrics-secret"})
    payload = {
        "redis_url": "redis://localhost:6379/0",
        "postgres_dsn": "postgresql://user:pass@localhost:5432/app",
        "metrics_token_env": "METRICS_TOKEN",
        "metrics_path": "metrics.prom",
        "rate_limit_per_minute": 60,
        "idempotency_ttl_hours": 24,
        "profile": "SABT_V1",
        "allow_get_fail_open": False,
        "unknown": "oops",
    }
    rid = "3f2504e04f8911d39a0c0305e82c3301"

    with pytest.raises(ConfigValidationError):
        await audited_config_parse(
            guard,
            payload,
            service=audit_env.service,
            actor_role=AuditActorRole.ADMIN,
            center_scope="center-001",
            resource_type="runtime-config",
            resource_id="primary",
            request_id=rid,
        )

    events = await audit_env.service.list_events(
        AuditQuery(action=AuditAction.CONFIG_REJECTED, limit=5)
    )
    assert events, audit_env.debug_context()
    assert events[-1].error_code == "CONFIG_INVALID_VALUE", audit_env.debug_context()
    assert events[-1].request_id == rid, audit_env.debug_context()
