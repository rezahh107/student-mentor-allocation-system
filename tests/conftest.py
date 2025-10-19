from __future__ import annotations

import json
import pathlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from prometheus_client import CollectorRegistry
from click.testing import CliRunner

from src.fakeredis import FakeStrictRedis
from src.repo_doctor.clock import tehran_clock
from src.repo_doctor.metrics import DoctorMetrics
from tools import reqs_doctor
from tools.reqs_doctor.clock import DeterministicClock


def pytest_addoption(parser):
    parser.addini("env", type="linelist", help="environment variables for tests")


@pytest.fixture()
def tehran_frozen_clock():
    return tehran_clock()


@pytest.fixture()
def metrics_registry(tmp_path: pathlib.Path) -> Iterator[DoctorMetrics]:
    metrics = DoctorMetrics(tmp_path / "metrics.prom")
    yield metrics
    metrics.registry = CollectorRegistry()


@pytest.fixture()
def fake_redis() -> Iterator[FakeStrictRedis]:
    client = FakeStrictRedis()
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture()
def clock() -> Iterator[DeterministicClock]:
    clk = DeterministicClock()
    yield clk
    clk.freeze(None)


@dataclass
class DoctorEnv:
    root: Path
    clock: DeterministicClock
    runner: CliRunner

    def make_namespace(self, name: str) -> Path:
        namespace = self.root / f"namespace_{name}_{uuid.uuid4().hex}"
        namespace.mkdir(parents=True, exist_ok=True)
        return namespace

    def run_with_retry(self, command: list[str], *, attempts: int = 3):
        last_output = None
        for attempt in range(1, attempts + 1):
            result = self.runner.invoke(reqs_doctor.app, command)
            if result.exit_code == 0:
                return result
            last_output = result.output
            self.clock.tick(seconds=attempt * 0.05)
        raise AssertionError(f"Retry exhausted: {last_output}")

    def debug(self) -> str:
        return json.dumps(
            {
                "timestamp": self.clock.now().isoformat(),
                "namespaces": sorted(p.name for p in self.root.glob("namespace_*")),
            },
            ensure_ascii=False,
        )


@pytest.fixture()
def doctor_env(tmp_path: Path, clock: DeterministicClock) -> Iterator[DoctorEnv]:
    base = tmp_path / f"reqs_doctor_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    env = DoctorEnv(root=base, clock=clock, runner=runner)
    yield env
    if base.exists():
        shutil.rmtree(base)
