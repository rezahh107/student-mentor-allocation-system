import datetime as dt
import asyncio
import uuid

import httpx

from phase6_import_to_sabt.app import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics
from phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _rows(year: int, center: int | None):
    return []


def test_render_base_via_testclient(tmp_path) -> None:
    unique = uuid.uuid4().hex
    config = AppConfig.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": f"ui-{unique}", "operation_timeout": 0.2},
            "database": {"dsn": "postgresql://user:pass@localhost/db", "statement_timeout_ms": 500},
            "auth": {"metrics_token": "token", "service_token": "svc"},
            "ratelimit": {"namespace": f"rl-{unique}", "requests": 5, "window_seconds": 60, "penalty_seconds": 120},
            "observability": {"service_name": "import-to-sabt", "metrics_namespace": f"import_to_sabt_{unique}"},
            "timezone": "Asia/Tehran",
            "enable_diagnostics": True,
        }
    )
    clock = FixedClock(dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc))
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    metrics = build_metrics(config.observability.metrics_namespace)
    ix_metrics = build_import_export_metrics()
    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=ix_metrics,
        data_provider=_rows,
    )
    rate_store = InMemoryKeyValueStore(namespace=f"rl-{unique}", clock=clock)
    idem_store = InMemoryKeyValueStore(namespace=f"idem-{unique}", clock=clock)
    app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
        workflow=workflow,
    )
    async def _invoke():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/ui/exports/new")

    response = asyncio.run(_invoke())
    assert response.status_code == 200, response.text
    html = response.text
    assert "lang=\"fa-IR\"" in html
    assert "dir=\"rtl\"" in html
    assert "hx-post" in html
