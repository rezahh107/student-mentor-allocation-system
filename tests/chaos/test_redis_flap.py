from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.reliability import Clock, RedisFlapInjector, ReliabilityMetrics
from src.reliability.logging_utils import JSONLogger


class FakeNow:
    def __init__(self) -> None:
        self.base = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
        self.calls = -1

    def __call__(self) -> datetime:
        self.calls += 1
        return self.base + timedelta(seconds=self.calls)


@pytest.fixture()
def clock() -> Clock:
    return Clock(ZoneInfo("UTC"), FakeNow())


@pytest.fixture()
def metrics() -> ReliabilityMetrics:
    return ReliabilityMetrics()


def test_export_under_redis_flap_no_slo_violation(tmp_path: Path, clock: Clock, metrics: ReliabilityMetrics) -> None:
    logger = JSONLogger("test.reliability")
    scenario = RedisFlapInjector(
        name="redis_export",
        metrics=metrics,
        logger=logger,
        clock=clock,
        reports_root=tmp_path,
    )
    def operation() -> dict[str, bool]:
        return {"ok": True}

    report = scenario.run(
        operation,
        fault_plan=[1, 0],
        correlation_id="rid-test",
        namespace="chaos-tests",
    )
    assert report["success"] is True
    assert report["attempts"] == 2
    assert report["duration_s"] >= 0.0
    chaos_success = metrics.chaos_incidents.labels(
        type="redis",
        scenario="redis_export",
        outcome="success",
        reason="completed",
        namespace="chaos-tests",
    )
    assert chaos_success._value.get() == 1.0

    retries = metrics.retries.labels(operation="chaos:redis_export", namespace="chaos-tests")
    assert retries._value.get() == 1.0

    report_file = tmp_path / "redis_export.json"
    payload = json.loads(report_file.read_text(encoding="utf-8"))
    assert payload["namespace"] == "chaos-tests"
    assert payload["injected"] == 1
