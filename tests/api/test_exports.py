import asyncio
import datetime as dt
import uuid

import httpx
import pytest

from sma.phase6_import_to_sabt.api import HMACSignedURLProvider
from sma.phase6_import_to_sabt.app import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics

from tests.export.helpers import build_job_runner, make_row


def _build_config(unique: str) -> AppConfig:
    return AppConfig.model_validate(
        {
            "redis": {
                "dsn": "redis://localhost:6379/0",
                "namespace": f"test-{unique}",
                "operation_timeout": 0.2,
            },
            "database": {
                "dsn": "postgresql://user:pass@localhost/db",
                "statement_timeout_ms": 500,
            },
            "auth": {"metrics_token": "token", "service_token": "service"},
            "ratelimit": {
                "namespace": f"rl-{unique}",
                "requests": 5,
                "window_seconds": 60,
                "penalty_seconds": 120,
            },
            "observability": {
                "service_name": "import-to-sabt",
                "metrics_namespace": f"import_to_sabt_{unique}",
            },
            "timezone": "Asia/Tehran",
        }
    )


@pytest.fixture
def export_stack(tmp_path):
    created = []

    def _build(rows):
        unique = uuid.uuid4().hex
        base_path = tmp_path / unique
        base_path.mkdir()
        config = _build_config(unique)
        clock = FixedClock(dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc))
        timer = DeterministicTimer([0.01, 0.02, 0.03, 0.04])
        service_metrics = build_metrics(config.observability.metrics_namespace)
        runner, export_metrics = build_job_runner(base_path, rows, clock=clock)
        signer = HMACSignedURLProvider(secret="secret", clock=clock, base_url="/download")
        rate_store = InMemoryKeyValueStore(namespace=f"rl-{unique}", clock=clock)
        idem_store = InMemoryKeyValueStore(namespace=f"idem-{unique}", clock=clock)
        app = create_application(
            config,
            clock=clock,
            metrics=service_metrics,
            timer=timer,
            rate_limit_store=rate_store,
            idempotency_store=idem_store,
            readiness_probes={},
            workflow=None,
            export_runner=runner,
            export_metrics=export_metrics,
            export_logger=runner.logger,
            export_signer=signer,
        )
        gate = getattr(app.state, "export_readiness_gate", None)
        if gate is not None:
            gate.record_dependency(name="redis", healthy=True)
            gate.record_dependency(name="database", healthy=True)
            gate.record_cache_warm()
        created.append((runner, service_metrics))
        return app, runner

    yield _build

    for runner, service_metrics in created:
        if hasattr(runner, "redis") and runner.redis is not None:
            flush = getattr(runner.redis, "flushdb", None)
            if callable(flush):
                flush()
        reset = getattr(service_metrics, "reset", None)
        if callable(reset):
            reset()


def _debug_snapshot(app, runner) -> dict[str, object]:
    gate = getattr(app.state, "export_readiness_gate", None)
    ready = gate.ready() if gate is not None else False
    return {
        "jobs": sorted(runner.jobs.keys()),
        "ready": ready,
    }


def test_post_exports_201_csv(export_stack):
    rows = [make_row(idx=i) for i in range(1, 4)]
    app, runner = export_stack(rows)

    async def _flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            correlation = f"req-{uuid.uuid4().hex}"
            response = await client.post(
                "/api/exports",
                json={"year": 1402, "center": 1, "format": "csv"},
                headers={
                    "Authorization": "Bearer service",
                    "Idempotency-Key": f"key-{uuid.uuid4().hex}",
                    "X-Role": "ADMIN",
                    "X-Client-ID": "client-1",
                    "X-Request-ID": correlation,
                },
            )
            assert response.status_code == 202, (
                f"POST failed: {response.status_code} -> {response.text}; "
                f"ctx={_debug_snapshot(app, runner)}"
            )
            data = response.json()
            assert data["middleware_chain"] == ["ratelimit", "idempotency", "auth"]
            assert data["format"] == "csv"
            await asyncio.to_thread(runner.await_completion, data["job_id"])
            status = await client.get(
                f"/api/exports/{data['job_id']}",
                headers={"X-Role": "ADMIN", "Authorization": "Bearer service"},
            )
            assert status.status_code == 200, (
                f"Status lookup failed: {status.status_code} -> {status.text}; "
                f"ctx={_debug_snapshot(app, runner)}"
            )
            payload = status.json()
            assert payload["status"] == "SUCCESS"
            assert payload["files"], f"No files; ctx={_debug_snapshot(app, runner)}"
            first = payload["files"][0]
            assert first["url"].startswith("/download"), first
            assert payload["manifest"]["format"] == "csv"
            return data

    result = asyncio.run(_flow())
    assert result["status"] == "PENDING"


def test_backcompat_get_csv_202_with_deprecation(export_stack):
    rows = [make_row(idx=i) for i in range(1, 3)]
    app, runner = export_stack(rows)

    async def _legacy_flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            correlation = f"legacy-{uuid.uuid4().hex}"
            response = await client.get(
                "/api/exports/csv",
                params={"year": 1402, "center": 1},
                headers={
                    "X-Role": "ADMIN",
                    "Authorization": "Bearer service",
                    "X-Request-ID": correlation,
                },
            )
            assert response.status_code == 202, (
                f"Legacy endpoint failed: {response.status_code} -> {response.text}; "
                f"ctx={_debug_snapshot(app, runner)}"
            )
            assert response.headers.get("Deprecation") == "true"
            assert response.headers.get("Link") == "</api/exports?format=csv>; rel=\"successor-version\""
            assert response.headers.get("Sunset") == "2025-03-01T00:00:00Z"
            initial = response.json()
            await asyncio.to_thread(runner.await_completion, initial["job_id"])
            status = await client.get(
                f"/api/exports/{initial['job_id']}",
                headers={"X-Role": "ADMIN", "Authorization": "Bearer service"},
            )
            assert status.status_code == 200, status.text
            repeat = await client.get(
                "/api/exports/csv",
                params={"year": 1402, "center": 1},
                headers={
                    "X-Role": "ADMIN",
                    "Authorization": "Bearer service",
                    "X-Request-ID": correlation,
                },
            )
            assert repeat.status_code == 202
            assert repeat.json()["job_id"] == initial["job_id"]
            return initial

    result = asyncio.run(_legacy_flow())
    assert result["format"] == "csv"
