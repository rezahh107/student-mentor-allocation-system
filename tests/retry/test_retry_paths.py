from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from phase6_import_to_sabt.job_runner import ExportJobRunner
from phase6_import_to_sabt.logging_utils import ExportLogger
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.models import (
    ExportFilters,
    ExportManifest,
    ExportManifestFile,
    ExportOptions,
    ExportSnapshot,
    ExportJobStatus,
    SABT_V1_PROFILE,
)
from phase6_import_to_sabt.sanitization import deterministic_jitter


class FlakyExporter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self._attempts = 0

    def run(self, *, filters, options, snapshot, clock_now):  # noqa: ANN001
        self._attempts += 1
        if self._attempts < 3:
            raise OSError("transient")
        file = ExportManifestFile(
            name="noop.csv",
            sha256="deadbeef",
            row_count=1,
            byte_size=128,
        )
        return ExportManifest(
            profile=SABT_V1_PROFILE,
            filters=filters,
            snapshot=snapshot,
            generated_at=clock_now,
            total_rows=1,
            files=(file,),
        )


class NoopRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setnx(self, key: str, value: str, ex: int | None = None) -> bool:
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        pass

    def hgetall(self, key: str) -> dict[str, str]:
        return {}

    def expire(self, key: str, ttl: int) -> None:
        pass

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_exponential_backoff_and_jitter(tmp_path):
    exporter = FlakyExporter(tmp_path)
    metrics = ExporterMetrics()
    logger = ExportLogger()
    clock = lambda: datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    runner = ExportJobRunner(
        exporter=exporter,
        redis=NoopRedis(),
        metrics=metrics,
        logger=logger,
        clock=clock,
        max_retries=3,
    )
    delays: list[float] = []
    with patch("src.phase6_import_to_sabt.job_runner.time.sleep", lambda delay: delays.append(delay)):
        job = runner.submit(
            filters=ExportFilters(year=1402, center=1),
            options=ExportOptions(output_format="csv"),
            idempotency_key="retry",
            namespace="retry",
            correlation_id="retry",
        )
        runner.await_completion(job.id)
    assert len(delays) == 2
    expected_first = deterministic_jitter(0.1, 1, job.id)
    expected_second = deterministic_jitter(0.1, 2, job.id)
    assert delays == [expected_first, expected_second]
    finished = runner.get_job(job.id)
    assert finished and finished.status == ExportJobStatus.SUCCESS
