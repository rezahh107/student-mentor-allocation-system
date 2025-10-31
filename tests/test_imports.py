"""Smoke tests for canonical import paths."""

from __future__ import annotations

import datetime as dt
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.append(str(SRC))

from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture
def minimal_config() -> AppConfig:
    return AppConfig(
        redis={"dsn": "redis://localhost:6379/0", "namespace": "import_to_sabt_test"},
        database={"dsn": "postgresql+asyncpg://localhost/test"},
        auth={
            "metrics_token": "metrics-token-123456",
            "service_token": "service-token-123456",
            "tokens_env_var": "TOKENS",
            "download_signing_keys_env_var": "DOWNLOAD_SIGNING_KEYS",
            "download_url_ttl_seconds": 900,
        },
    )


def test_create_application_smoke(minimal_config: AppConfig) -> None:
    instant = dt.datetime.fromisoformat("2024-01-01T00:00:00+00:00")
    fixed_clock = FixedClock(instant=instant)
    rate_store = InMemoryKeyValueStore("ratelimit-test", fixed_clock)
    idem_store = InMemoryKeyValueStore("idempotency-test", fixed_clock)
    app = create_application(
        config=minimal_config,
        clock=fixed_clock,
        metrics=build_metrics("import_to_sabt_test"),
        timer=DeterministicTimer(),
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
        readiness_probes={},
    )
    assert app.title == "ImportToSabt"
    paths = set(app.openapi()["paths"].keys())
    assert "/api/xlsx/uploads" in paths
    middleware_chain = [mw.cls.__name__ for mw in app.user_middleware]
    assert middleware_chain[:3] == [
        "RateLimitMiddleware",
        "IdempotencyMiddleware",
        "AuthMiddleware",
    ]


@pytest.mark.parametrize(
    "module_path",
    [
        "phase6_import_to_sabt.app.config",
        "phase6_import_to_sabt.app.errors",
        "phase6_import_to_sabt.app.middleware",
        "phase6_import_to_sabt.security.signer",
        "phase6_import_to_sabt.xlsx.workflow",
    ],
)
def test_importable_modules(module_path: str) -> None:
    assert importlib.import_module(module_path)
