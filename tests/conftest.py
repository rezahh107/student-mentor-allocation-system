from __future__ import annotations

import json
import pathlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import prometheus_client
import prometheus_client.registry as prometheus_registry
import pytest
from click.testing import CliRunner
from freezegun import freeze_time
from prometheus_client import CollectorRegistry

from sma._local_fakeredis import FakeStrictRedis
from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.metrics import DoctorMetrics
from tools import reqs_doctor
from tools.reqs_doctor.clock import DeterministicClock

FREEZE_INSTANT = datetime(2024, 3, 20, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))
FORBIDDEN_TIME_PATTERNS = ("datetime.now(", "datetime.utcnow(", "time.time(", "time.sleep(")
WALL_CLOCK_ALLOWLIST = {
    pathlib.Path("src/sma/core/system_clock.py"),
    pathlib.Path("src/sma/core/clock.py"),
    pathlib.Path("src/sma/phase6_import_to_sabt/app/clock.py"),
    pathlib.Path("src/sma/_local_fakeredis/__init__.py"),
    pathlib.Path("src/sma/git_sync_verifier/clock.py"),
}
SCAN_ROOTS = (pathlib.Path("src/sma"),)


def _scan_wall_clock(repo_root: pathlib.Path) -> tuple[list[tuple[str, str]], list[str]]:
    banned: list[tuple[str, str]] = []
    scanned: list[str] = []
    for relative_root in SCAN_ROOTS:
        base = repo_root / relative_root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(repo_root)
            rel_str = str(rel)
            scanned.append(rel_str)
            if rel in WALL_CLOCK_ALLOWLIST:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # pragma: no cover - defensive for stub files
                continue
            for pattern in FORBIDDEN_TIME_PATTERNS:
                if pattern in text:
                    banned.append((rel_str, pattern))
                    break
    return banned, scanned


def pytest_configure(config: pytest.Config) -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    banned, scanned = _scan_wall_clock(repo_root)
    config._repo_wall_clock_guard = {  # type: ignore[attr-defined]
        "banned": banned,
        "scanned": scanned,
    }


@pytest.fixture(scope="session", autouse=True)
def freeze_tehran_time() -> Iterator[object]:
    with freeze_time(FREEZE_INSTANT, tick=False) as frozen:
        yield frozen


@pytest.fixture(scope="function", autouse=True)
def fresh_metrics_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[CollectorRegistry]:
    registry = CollectorRegistry()
    monkeypatch.setattr(prometheus_registry, "REGISTRY", registry, raising=False)
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry, raising=False)
    yield registry


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
