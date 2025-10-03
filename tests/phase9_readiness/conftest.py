from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Iterator

import pytest
from freezegun import freeze_time
from prometheus_client import CollectorRegistry
from zoneinfo import ZoneInfo

from src.phase2_counter_service.academic_year import AcademicYearProvider
from src.phase9_readiness import ReadinessMetrics, ReadinessOrchestrator, RetryPolicy
from src.phase9_readiness.orchestrator import (
    AcceptanceChecklistItem,
    EnvironmentConfig,
    TokenConfig,
    UATScenario,
)
from src.fakeredis import FakeStrictRedis
from src.reliability.clock import Clock
from src.reliability.logging_utils import JSONLogger, configure_logging


@pytest.fixture(scope="function")
def namespace() -> str:
    return f"phase9-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="function")
def clean_state(tmp_path: Path) -> Iterator[dict[str, Any]]:
    redis_client = FakeStrictRedis()
    registry = CollectorRegistry()
    reports_root = tmp_path / "reports"
    docs_root = tmp_path / "docs"
    configure_logging()
    ctx = {
        "redis": redis_client,
        "registry": registry,
        "reports": reports_root,
        "docs": docs_root,
    }
    redis_client.flushall()
    if reports_root.exists():
        shutil.rmtree(reports_root)
    if docs_root.exists():
        shutil.rmtree(docs_root)
    yield ctx
    redis_client.flushall()
    if reports_root.exists():
        shutil.rmtree(reports_root)
    if docs_root.exists():
        shutil.rmtree(docs_root)


@pytest.fixture(scope="function")
def env_config(namespace: str) -> EnvironmentConfig:
    data = {
        "namespace": namespace,
        "tokens": TokenConfig(metrics_read="M" * 24, download_signing="S" * 48),
        "dsns": {"redis": "redis://localhost/0", "postgres": "postgresql://localhost/db"},
    }
    return EnvironmentConfig(**data)


@pytest.fixture(scope="function")
def metrics(clean_state: dict[str, Any]) -> ReadinessMetrics:
    return ReadinessMetrics(clean_state["registry"])


@pytest.fixture(scope="function")
def clock() -> Clock:
    return Clock(ZoneInfo("Asia/Tehran"))


@pytest.fixture(scope="function")
def retry_waits() -> list[float]:
    return []


@pytest.fixture(scope="function")
def retry_policy_factory(
    metrics: ReadinessMetrics, clock: Clock, namespace: str, retry_waits: list[float]
) -> Callable[[str], RetryPolicy]:
    def factory(operation: str) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.05,
            metrics=metrics,
            clock=clock,
            namespace=namespace,
            wait_strategy=retry_waits.append,
        )

    return factory


@pytest.fixture(scope="function")
def logger() -> JSONLogger:
    return JSONLogger("phase9.tests")


@pytest.fixture(scope="function")
def year_provider() -> AcademicYearProvider:
    return AcademicYearProvider({"1402": "02"})


@pytest.fixture(scope="function")
def orchestrator(
    clean_state: dict[str, Any],
    env_config: EnvironmentConfig,
    metrics: ReadinessMetrics,
    clock: Clock,
    logger: JSONLogger,
    retry_policy_factory: Callable[[str], RetryPolicy],
    year_provider: AcademicYearProvider,
) -> ReadinessOrchestrator:
    return ReadinessOrchestrator(
        output_root=clean_state["reports"],
        docs_root=clean_state["docs"],
        env_config=env_config,
        metrics=metrics,
        clock=clock,
        logger=logger,
        retry_policy_factory=retry_policy_factory,
        year_provider=year_provider,
    )


@pytest.fixture(scope="function")
def frozen_time() -> Iterator[None]:
    with freeze_time("2024-03-20T10:00:00+0400", tz_offset=4) as frozen:
        yield frozen


def get_debug_context(state: dict[str, Any]) -> dict[str, Any]:
    redis_client = state["redis"]
    return {
        "redis_keys": sorted(redis_client.keys()),
        "namespace": state.get("namespace"),
        "reports": sorted(path.name for path in state["reports"].glob("*")) if state["reports"].exists() else [],
    }


__all__ = [
    "AcceptanceChecklistItem",
    "EnvironmentConfig",
    "UATScenario",
    "get_debug_context",
]
