from __future__ import annotations

from pathlib import Path

import asyncio

import httpx
from zoneinfo import ZoneInfo

from src.reliability import (
    CleanupDaemon,
    Clock,
    DisasterRecoveryDrill,
    ReliabilityMetrics,
    ReliabilitySettings,
    RetentionEnforcer,
    create_reliability_app,
)
from src.reliability.logging_utils import JSONLogger


def test_order_and_token_guard(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    backups = tmp_path / "backups"
    artifacts.mkdir()
    backups.mkdir()

    settings = ReliabilitySettings.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": "mw"},
            "postgres": {
                "read_write_dsn": "postgresql://user:pass@localhost/db",
                "replica_dsn": "postgresql://user:pass@localhost/db",
            },
            "artifacts_root": str(artifacts),
            "backups_root": str(backups),
            "retention": {"age_days": 1, "max_total_bytes": 1024},
            "cleanup": {"part_max_age": 60, "link_ttl": 60},
            "tokens": {"metrics_read": "metrics-token"},
            "timezone": "UTC",
            "rate_limit": {"default_rule": {"requests": 5, "window_seconds": 60}, "fail_open": False},
            "idempotency": {"ttl_seconds": 3600, "storage_prefix": "idem"},
        }
    )

    metrics = ReliabilityMetrics()
    logger = JSONLogger("test.mw")
    clock = Clock(ZoneInfo("UTC"))
    retention = RetentionEnforcer(
        artifacts_root=artifacts,
        backups_root=backups,
        config=settings.retention,
        metrics=metrics,
        clock=clock,
        logger=logger,
        report_path=tmp_path / "retention_report.json",
        csv_report_path=tmp_path / "retention_report.csv",
        namespace="mw-tests",
    )
    cleanup = CleanupDaemon(
        artifacts_root=artifacts,
        backups_root=backups,
        config=settings.cleanup,
        metrics=metrics,
        clock=clock,
        logger=logger,
        registry_path=artifacts / "signed_urls.json",
        namespace="mw-tests",
        report_path=tmp_path / "cleanup_report.json",
    )
    drill = DisasterRecoveryDrill(
        backups_root=backups,
        metrics=metrics,
        logger=logger,
        clock=clock,
        report_path=tmp_path / "dr_report.json",
    )

    app = create_reliability_app(
        settings=settings,
        metrics=metrics,
        retention=retention,
        cleanup=cleanup,
        drill=drill,
        logger=logger,
        clock=clock,
    )

    async def _request() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post(
                "/retention/enforce",
                headers={
                    "Authorization": "Bearer metrics-token",
                    "Idempotency-Key": "mw-1",
                    "X-RateLimit-Key": "mw",
                    "X-Request-ID": "rid-1",
                },
            )

    response = asyncio.run(_request())
    assert response.status_code == 200
    assert response.headers["X-Middleware-Order"] == "RateLimit,Idempotency,Auth"

    async def _metrics(token: str | None) -> int:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            res = await client.get("/metrics", headers=headers)
        return res.status_code

    unauthorized = asyncio.run(_metrics(None))
    assert unauthorized == 401

    authorized = asyncio.run(_metrics("metrics-token"))
    assert authorized == 200


def test_order_enforced() -> None:
    from ops.middleware import MIDDLEWARE_CHAIN

    assert MIDDLEWARE_CHAIN == (
        "RateLimit",
        "Idempotency",
        "Auth",
    ), "Middleware order must remain RateLimit → Idempotency → Auth"
