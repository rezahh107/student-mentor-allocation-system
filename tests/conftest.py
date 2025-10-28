from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import shutil
import tempfile
import uuid
import weakref
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
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
from sma.testing.state import get_test_namespace, maybe_connect_redis
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
STATE_LOGGER = logging.getLogger("tests.state_hygiene")
_FAKE_REDIS_INSTANCES: "weakref.WeakSet[FakeStrictRedis]" = weakref.WeakSet()


def _track_fake_redis_instances() -> None:
    original_init = getattr(FakeStrictRedis, "__init__")

    if getattr(original_init, "_state_tracking_enabled", False):
        return

    def _tracked_init(self: FakeStrictRedis, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        original_init(self, *args, **kwargs)
        _FAKE_REDIS_INSTANCES.add(self)

    setattr(_tracked_init, "_state_tracking_enabled", True)
    FakeStrictRedis.__init__ = _tracked_init  # type: ignore[assignment]


_track_fake_redis_instances()


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


@pytest.fixture()
def rid(request: pytest.FixtureRequest) -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    digest = hashlib.blake2s(request.node.nodeid.encode("utf-8"), digest_size=8).hexdigest()
    return f"rid-{worker}-{digest}"


def _emit_state_log(event: str, correlation_id: str, namespace: str, **extra: Any) -> None:
    payload = {
        "correlation_id": correlation_id,
        "event": event,
        "namespace": namespace,
        **extra,
    }
    STATE_LOGGER.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


_DB_RESET_MISSING_LOGGED = False


def _reset_test_database(correlation_id: str, namespace: str) -> None:
    global _DB_RESET_MISSING_LOGGED
    try:
        from sma.testing import reset_db  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - optional hook
        if not _DB_RESET_MISSING_LOGGED:
            _emit_state_log(
                "db-reset-missing",
                correlation_id,
                namespace,
                message="هشدار: هوک بازنشانی پایگاه‌داده پیدا نشد؛ انجام نشد (بدون اثر).",
            )
            _DB_RESET_MISSING_LOGGED = True
        return

    try:
        reset_db()
        _emit_state_log("db-reset-success", correlation_id, namespace)
    except Exception as exc:  # pragma: no cover - defensive
        _emit_state_log("db-reset-failed", correlation_id, namespace, error=str(exc))


def _flush_fake_redis_clients(correlation_id: str, namespace: str) -> None:
    for client in list(_FAKE_REDIS_INSTANCES):
        try:
            client.flushall()
        except Exception as exc:  # pragma: no cover - defensive
            _emit_state_log("fakeredis-flush-error", correlation_id, namespace, error=str(exc))


def _flush_real_redis_namespace(client: Any, namespace: str, correlation_id: str) -> None:
    pattern = f"{namespace}:*"
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            client.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break
    _emit_state_log("redis-namespace-flushed", correlation_id, namespace, keys=deleted)


@pytest.fixture(scope="function", autouse=True)
def fresh_state_namespaces(rid: str) -> Iterator[None]:
    namespace = get_test_namespace()
    correlation_id = rid
    redis_client = maybe_connect_redis(correlation_id=correlation_id)

    if redis_client is None:
        _emit_state_log(
            "redis-unavailable",
            correlation_id,
            namespace,
            message="پاک‌سازی فضای آزمون Redis انجام نشد؛ اتصال در دسترس نیست.",
        )

    _flush_fake_redis_clients(correlation_id, namespace)
    if redis_client is not None:
        _flush_real_redis_namespace(redis_client, namespace, correlation_id)

    _reset_test_database(correlation_id, namespace)

    yield

    _flush_fake_redis_clients(correlation_id, namespace)
    if redis_client is not None:
        _flush_real_redis_namespace(redis_client, namespace, correlation_id)

    _reset_test_database(correlation_id, namespace)


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


@pytest.fixture(autouse=True)
def clean_env():
    keep = {"PATH", "PYTHONPATH", "METRICS_TOKEN", "BASE_URL"}
    snapshot = dict(os.environ)
    yield
    for k in list(os.environ):
        if k not in keep and os.environ.get(k) != snapshot.get(k):
            if k in snapshot:
                os.environ[k] = snapshot[k]
            else:
                os.environ.pop(k, None)


@pytest.fixture
def temp_home(monkeypatch):
    d = tempfile.mkdtemp(prefix="sma_tmp_")
    monkeypatch.setenv("HOME", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)
