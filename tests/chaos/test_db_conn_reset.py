from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sma.reliability import Clock, DbConnectionResetInjector, ReliabilityMetrics
from sma.reliability.logging_utils import JSONLogger


class FakeNow:
    def __init__(self) -> None:
        self.base = datetime(2024, 2, 1, tzinfo=ZoneInfo("UTC"))
        self.calls = -1

    def __call__(self) -> datetime:
        self.calls += 1
        return self.base + timedelta(milliseconds=100 * self.calls)


@pytest.fixture()
def clock() -> Clock:
    return Clock(ZoneInfo("UTC"), FakeNow())


@pytest.fixture()
def metrics() -> ReliabilityMetrics:
    return ReliabilityMetrics()


def test_upload_survives_conn_reset_with_retry(tmp_path: Path, clock: Clock, metrics: ReliabilityMetrics) -> None:
    logger = JSONLogger("test.pg")
    scenario = DbConnectionResetInjector(
        name="db_reset",
        metrics=metrics,
        logger=logger,
        clock=clock,
        reports_root=tmp_path,
    )
    def upload() -> str:
        return "uploaded"

    report = scenario.run(
        upload,
        fault_plan=[1, 1, 0],
        correlation_id="pg-rid",
        namespace="pg-chaos",
    )
    assert report["success"] is True
    assert report["attempts"] == 3

    success_metric = metrics.chaos_incidents.labels(
        type="postgres",
        scenario="db_reset",
        outcome="success",
        reason="completed",
        namespace="pg-chaos",
    )
    assert success_metric._value.get() == 1.0

    retry_metric = metrics.retries.labels(operation="chaos:db_reset", namespace="pg-chaos")
    assert retry_metric._value.get() == 2.0

    json_payload = (tmp_path / "db_reset.json").read_text(encoding="utf-8")
    assert "pg-chaos" in json_payload
