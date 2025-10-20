from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

from prometheus_client import CollectorRegistry

from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics


@dataclass
class FakeDistribution:
    name: str
    release: str

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}

    @property
    def version(self) -> str:  # type: ignore[override]
        return self.release


class FrozenClock:
    def __init__(self, *, start: datetime | float) -> None:
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            self._start = start.timestamp()
        else:
            self._start = float(start)
        self._current = self._start

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._current, tz=timezone.utc)

    def monotonic(self) -> float:
        return self._current

    def advance(self, seconds: float) -> None:
        self._current += seconds


class DummyRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def setnx(self, key: str, value: str, ex: int | None = None) -> bool:
        if key in self._store:
            return False
        self._store[key] = value
        return True

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def keys(self, pattern: str = "*") -> list[str]:
        return list(self._store.keys())


@dataclass
class DummyJob:
    id: str
    status: str
    manifest: Any | None = None


class DummyRunner:
    def __init__(self, *, output_dir: Path) -> None:
        self.redis = DummyRedis()
        self.exporter = type("Exporter", (), {"output_dir": output_dir})()
        self.metrics = ExporterMetrics(CollectorRegistry())
        self.logger = ExportLogger()
        self._jobs: dict[str, DummyJob] = {}
        self._responses: Deque[DummyJob] = deque()

    def prime(self, job: DummyJob) -> None:
        self._jobs[job.id] = job
        self._responses.append(job)

    def submit(
        self,
        *,
        filters: Any,
        options: Any,
        idempotency_key: str,
        namespace: str,
    ) -> DummyJob:
        if self._responses:
            job = self._responses[0]
        else:
            job = DummyJob(id="job-1", status="PENDING")
            self._jobs[job.id] = job
            self._responses.append(job)
        return job

    def get_job(self, job_id: str) -> DummyJob | None:
        return self._jobs.get(job_id)
