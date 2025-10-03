from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from phase6_import_to_sabt.app.app_factory import create_application
from phase6_import_to_sabt.app.clock import FixedClock
from phase6_import_to_sabt.app.config import AppConfig
from phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from phase6_import_to_sabt.app.timing import DeterministicTimer
from phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture()
def metrics_context() -> Dict[str, object]:
    unique = uuid4().hex
    config = AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": f"import_to_sabt_metrics_{unique}"},
        database={"dsn": "postgresql://localhost/import_to_sabt"},
        auth={
            "metrics_token": f"metrics-{unique}",
            "service_token": f"service-{unique}",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_KEYS",
            "download_url_ttl_seconds": 900,
        },
        timezone="Asia/Tehran",
    )
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    timer = DeterministicTimer([0.0, 0.0, 0.0])
    registry_namespace = f"import_to_sabt_metrics_{unique}"
    metrics = build_metrics(registry_namespace)
    rate_store = InMemoryKeyValueStore(f"rate:{unique}", clock)
    idem_store = InMemoryKeyValueStore(f"idem:{unique}", clock)
    app = create_application(
        config=config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    yield {
        "app": app,
        "token": config.auth.metrics_token,
        "rate_store": rate_store,
        "idem_store": idem_store,
    }
    rate_store._store.clear()
    idem_store._store.clear()


def test_metrics_requires_token(metrics_context: Dict[str, object]) -> None:
    app = metrics_context["app"]
    with TestClient(app) as client:
        response = client.get("/metrics")
        assert response.status_code in {401, 403}, {
            "status": response.status_code,
            "body": response.text,
        }
        authed = client.get("/metrics", headers={"X-Metrics-Token": metrics_context["token"]})
        assert authed.status_code == 200, {
            "status": authed.status_code,
            "body": authed.text[:200],
        }
        assert authed.text.startswith("# HELP"), authed.text[:200]
