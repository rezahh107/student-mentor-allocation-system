from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sma.audit.enums import AuditAction, AuditActorRole, AuditOutcome
from sma.audit.repository import AuditRepository
from sma.audit.service import AuditService, build_metrics as build_audit_metrics
from sma.reliability.clock import Clock

from tests.helpers.jwt_factory import build_jwt
from tests.rbac.test_admin_vs_manager import _auth_header, api_client


def _adapt_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise TypeError("sqlite adapters require timezone-aware datetimes")
    return value.isoformat()


def _convert_datetime(raw: bytes) -> datetime:
    return datetime.fromisoformat(raw.decode("utf-8"))


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("timestamp", _convert_datetime)
sqlite3.register_converter("datetime", _convert_datetime)


def _counter_total(counter, **labels) -> float:
    sample = next(s for s in counter.collect()[0].samples if all(s.labels.get(k) == v for k, v in labels.items()))
    return sample.value


def test_auth_and_audit_metrics(api_client: tuple) -> None:
    client, creds = api_client
    metrics = client.app.state.service_metrics

    now = creds["now_ts"]
    admin_token = build_jwt(
        secret=creds["service_secret"],
        subject="auth-ok",
        role="ADMIN",
        iat=now,
        exp=now + 3600,
    )
    client.get("/api/jobs", headers=_auth_header(admin_token))

    client.get("/api/jobs", headers={"Authorization": "Bearer invalid-token"})

    ok_total = _counter_total(metrics.auth_ok_total, role="ADMIN")
    fail_total = _counter_total(metrics.auth_fail_total, reason="unknown_token")
    assert ok_total >= 1
    assert fail_total >= 1


def test_audit_metrics_increment(tmp_path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
            "detect_types": sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        },
        poolclass=StaticPool,
    )
    repository = AuditRepository(engine)
    asyncio.run(repository.init())
    audit_metrics = build_audit_metrics()
    clock = Clock(timezone=ZoneInfo("Asia/Tehran"), _now_factory=lambda: datetime(2024, 6, 1, tzinfo=timezone.utc))
    service = AuditService(repository=repository, clock=clock, metrics=audit_metrics)

    asyncio.run(
        service.record_event(
            actor_role=AuditActorRole.ADMIN,
            center_scope=None,
            action=AuditAction.AUTHN_OK,
            resource_type="auth",
            resource_id="login",
            request_id="a" * 32,
            outcome=AuditOutcome.OK,
        )
    )
    asyncio.run(
        service.record_event(
            actor_role=AuditActorRole.MANAGER,
            center_scope="10",
            action=AuditAction.AUTHN_FAIL,
            resource_type="auth",
            resource_id="login",
            request_id="b" * 32,
            outcome=AuditOutcome.ERROR,
        )
    )

    ok = _counter_total(audit_metrics.events_total, action="AUTHN_OK", outcome="OK")
    fail = _counter_total(audit_metrics.events_total, action="AUTHN_FAIL", outcome="ERROR")
    assert ok == 1
    assert fail == 1

