import datetime as dt
import asyncio
import uuid

import httpx

from sma.phase6_import_to_sabt.app import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.app.utils import get_debug_context
from sma.phase6_import_to_sabt.obs.metrics import build_metrics


def test_metrics_endpoint_is_public(tmp_path) -> None:
    unique = uuid.uuid4().hex
    config = AppConfig.model_validate(
        {
            "redis": {"dsn": "redis://localhost:6379/0", "namespace": f"metrics-{unique}", "operation_timeout": 0.2},
            "database": {"dsn": "postgresql://user:pass@localhost/db", "statement_timeout_ms": 500},
            "auth": {"metrics_token": "token", "service_token": "svc"},
            "ratelimit": {"namespace": f"rl-{unique}", "requests": 5, "window_seconds": 60, "penalty_seconds": 120},
            "observability": {"service_name": "import-to-sabt", "metrics_namespace": f"import_to_sabt_{unique}"},
            "timezone": "Asia/Tehran",
        }
    )
    clock = FixedClock(dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc))
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    metrics = build_metrics(config.observability.metrics_namespace)
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
        workflow=None,
    )
    async def _invoke():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/metrics")

    response = asyncio.run(_invoke())
    assert response.status_code == 200, get_debug_context(app)
    assert response.text.startswith("# HELP")
