from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import anyio
from httpx import ASGITransport, AsyncClient

from src.phase6_import_to_sabt.app.app_factory import create_application
from src.phase6_import_to_sabt.app.clock import FixedClock
from src.phase6_import_to_sabt.app.config import AppConfig
from src.phase6_import_to_sabt.app.probes import ProbeResult
from src.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from src.phase6_import_to_sabt.obs.metrics import build_metrics
from src.phase6_import_to_sabt.app.timing import MonotonicTimer


async def _healthy_probe(_timeout: float) -> ProbeResult:
    return ProbeResult(component="dummy", healthy=True)


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": "ci-ui"},
            "database": {"dsn": "postgresql://localhost/db", "statement_timeout_ms": 500},
            "auth": {"metrics_token": "metrics-token", "service_token": "service-token"},
            "ratelimit": {"namespace": "ci-ui", "requests": 10, "window_seconds": 60, "penalty_seconds": 120},
            "observability": {"service_name": "ci-ui", "metrics_namespace": "ci_ui"},
            "timezone": "Asia/Tehran",
            "enable_diagnostics": False,
        }
    )


def test_ssr_template_is_htmx_ready_and_pii_free():
    clock = FixedClock(dt.datetime(2024, 1, 1, tzinfo=ZoneInfo("Asia/Tehran")))
    rate_store = InMemoryKeyValueStore(namespace="rate-ci", clock=clock)
    idem_store = InMemoryKeyValueStore(namespace="idem-ci", clock=clock)
    app = create_application(
        _build_config(),
        clock=clock,
        metrics=build_metrics("ci_ui_smoke"),
        timer=MonotonicTimer(),
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={"dummy": _healthy_probe},
    )
    async def _fetch() -> str:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/ui/exports")
            resp.raise_for_status()
            return resp.text

    content = anyio.run(_fetch)
    assert 'lang="fa-IR"' in content
    assert 'dir="rtl"' in content
    assert "Vazir" in content
    assert "htmx.org" in content
    assert 'hx-get="/api/exports"' in content
    assert 'hx-trigger="load"' in content
    assert not re.search(r"09\d{9}", content)
    assert not re.search(r"\b\d{10}\b", content)
