from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import os
import pathlib
import random
import shutil
import tempfile
import unicodedata
import uuid
import warnings
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import prometheus_client
import prometheus_client.registry as prometheus_registry
import pytest

if os.getenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "0") == "1":
    pytest_plugins: tuple[str, ...] = ("pytest_asyncio.plugin",)
else:
    pytest_plugins = ()

try:  # pragma: no cover - optional dependency guard for anyio
    from anyio.streams import memory as _anyio_memory

    _anyio_memory.MemoryObjectReceiveStream.__del__ = lambda self: None  # type: ignore[attr-defined]
    _anyio_memory.MemoryObjectSendStream.__del__ = lambda self: None  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - if anyio changes behaviour
    pass
from click.testing import CliRunner
from freezegun import freeze_time
from prometheus_client import CollectorRegistry

from sma._local_fakeredis import FakeStrictRedis
from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.metrics import DoctorMetrics
from sma.testing.state import get_test_namespace, maybe_connect_redis
from tests.integration.conftest import RedisNamespace
from tenacity import RetryCallState, Retrying, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base as TenacityWaitBase
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

T = TypeVar("T")

_DIGIT_FOLD_MAP = str.maketrans({
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
})
SCAN_ROOTS = (pathlib.Path("src/sma"),)
STATE_LOGGER = logging.getLogger("tests.state_hygiene")
_FAKE_REDIS_INSTANCES: "weakref.WeakSet[FakeStrictRedis]" = weakref.WeakSet()
_TRACKED_EVENT_LOOPS: "weakref.WeakSet[asyncio.AbstractEventLoop]" = weakref.WeakSet()
_ORIGINAL_NEW_EVENT_LOOP = asyncio.new_event_loop
_POLICY = asyncio.get_event_loop_policy()
_ORIGINAL_POLICY_NEW_LOOP = getattr(_POLICY, "new_event_loop", None)


def _tracked_new_event_loop() -> asyncio.AbstractEventLoop:
    loop = _ORIGINAL_NEW_EVENT_LOOP()
    _TRACKED_EVENT_LOOPS.add(loop)
    return loop


if not getattr(asyncio.new_event_loop, "_sma_tracked", False):
    setattr(asyncio.new_event_loop, "_sma_tracked", True)
    asyncio.new_event_loop = _tracked_new_event_loop  # type: ignore[assignment]


def _tracked_policy_new_event_loop() -> asyncio.AbstractEventLoop:
    loop = _ORIGINAL_POLICY_NEW_LOOP()
    _TRACKED_EVENT_LOOPS.add(loop)
    return loop


if _ORIGINAL_POLICY_NEW_LOOP and not getattr(_POLICY, "_sma_tracked_new_loop", False):
    setattr(_POLICY, "_sma_tracked_new_loop", True)
    _POLICY.new_event_loop = _tracked_policy_new_event_loop  # type: ignore[assignment]


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
    pythonwarnings = config.getoption("pythonwarnings", default=())
    actions: tuple[str, ...]
    if isinstance(pythonwarnings, (list, tuple)):
        actions = tuple(str(item) for item in pythonwarnings if str(item))
    elif isinstance(pythonwarnings, str) and pythonwarnings:
        actions = (pythonwarnings,)
    else:
        actions = ()
    for action in actions:
        warnings.simplefilter(action)
        os.environ.setdefault("PYTHONWARNINGS", action)


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_results_root() -> Iterator[Path]:
    base = Path("test-results")
    baseline = {
        base / "junit.xml",
        base / "pytest-summary.json",
        base / "pytest.log",
        base / "report.html",
    }
    base.mkdir(parents=True, exist_ok=True)
    for path in list(base.iterdir()):
        if path in baseline:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    previous_metrics = os.environ.get("PYTEST_PERF_METRICS_PATH")
    metrics_path = base / "performance-metrics.json"
    os.environ["PYTEST_PERF_METRICS_PATH"] = str(metrics_path)
    try:
        yield base
    finally:
        if previous_metrics is None:
            os.environ.pop("PYTEST_PERF_METRICS_PATH", None)
        else:
            os.environ["PYTEST_PERF_METRICS_PATH"] = previous_metrics


@pytest.fixture(scope="session", autouse=True)
def freeze_tehran_time() -> Iterator[object]:
    with freeze_time(FREEZE_INSTANT, tick=False) as frozen:
        yield frozen


@pytest.fixture(scope="session", autouse=True)
def _close_tracked_event_loops() -> Iterator[None]:
    try:
        yield
    finally:
        for loop in list(_TRACKED_EVENT_LOOPS):
            if loop.is_closed():
                continue
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            finally:
                loop.close()
        asyncio.new_event_loop = _ORIGINAL_NEW_EVENT_LOOP
        if _ORIGINAL_POLICY_NEW_LOOP is not None:
            _POLICY.new_event_loop = _ORIGINAL_POLICY_NEW_LOOP
            setattr(_POLICY, "_sma_tracked_new_loop", False)


@pytest.fixture(scope="function", autouse=True)
def fresh_metrics_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[CollectorRegistry]:
    registry = CollectorRegistry()
    monkeypatch.setattr(prometheus_registry, "REGISTRY", registry, raising=False)
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry, raising=False)
    yield registry


@pytest.fixture(autouse=True)
def _cleanup_event_loops_function() -> Iterator[None]:
    try:
        yield
    finally:
        for loop in list(_TRACKED_EVENT_LOOPS):
            if loop.is_closed() or loop.is_running():
                continue
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            finally:
                loop.close()


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


def _normalize_label(raw: str) -> str:
    collapsed = raw.replace("\ufeff", "").replace("\u200c", "")
    folded = collapsed.translate(_DIGIT_FOLD_MAP)
    return unicodedata.normalize("NFKC", folded)


def _normalize_attempts(value: Any) -> int:
    if value in (None, "", "0"):
        return 3
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, number)


def _normalize_exception_types(value: Any) -> tuple[type[BaseException], ...]:
    if value in (None, "", "0", 0):
        return (Exception,)
    if isinstance(value, type) and issubclass(value, BaseException):
        return (value,)
    if isinstance(value, (list, tuple, set)):
        normalized: list[type[BaseException]] = []
        for candidate in value:
            if isinstance(candidate, type) and issubclass(candidate, BaseException):
                normalized.append(candidate)
        return tuple(normalized) if normalized else (Exception,)
    return (Exception,)


def _seed_from_label(label: str) -> int:
    digest = hashlib.blake2s(label.encode("utf-8"), digest_size=16).digest()
    return int.from_bytes(digest, "big", signed=False)


def _normalize_delay(value: Any) -> float:
    if value in (None, "", "0", 0):
        return 0.1
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.1
    return max(parsed, 0.0)


class _DeterministicExponential(TenacityWaitBase):
    """Tenacity wait strategy with seeded jitter for deterministic retries."""

    def __init__(
        self, *, initial: float, maximum: float, jitter: float, rng: random.Random
    ) -> None:
        self._initial = max(initial, 0.0) or 0.1
        self._maximum = max(maximum, self._initial)
        self._jitter = max(jitter, 0.0)
        self._rng = rng

    def __call__(self, retry_state: RetryCallState) -> float:
        attempt_index = max(retry_state.attempt_number - 1, 0)
        base_delay = self._initial * (2 ** attempt_index)
        jitter = self._rng.uniform(0.0, self._jitter) if self._jitter > 0 else 0.0
        return min(self._maximum, base_delay + jitter)


def retry(
    *,
    times: Any = 3,
    delay: Any = 0.1,
    exceptions: Any = Exception,
    jitter: float = 0.1,
    label: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    normalized_attempts = _normalize_attempts(times)
    base_delay = _normalize_delay(delay)
    exception_types = _normalize_exception_types(exceptions)
    normalized_label = _normalize_label(label or "tests.retry")

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        correlation_id = f"{func.__module__}.{func.__name__}"

        def _log_state(state: RetryCallState, event: str) -> None:
            payload = {
                "attempt": state.attempt_number,
                "elapsed": state.seconds_since_start,
                "sleep": getattr(getattr(state, "next_action", None), "sleep", None),
                "error": str(state.outcome.exception()) if state.outcome.failed else None,
            }
            _emit_state_log(event, correlation_id, normalized_label, **payload)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            seed_label = f"{normalized_label}:{correlation_id}"
            rng = random.Random(_seed_from_label(seed_label))
            max_delay = max(base_delay, 0.1) * (2 ** (normalized_attempts - 1))
            wait = _DeterministicExponential(
                initial=base_delay if base_delay > 0 else 0.1,
                maximum=max_delay,
                jitter=float(jitter),
                rng=rng,
            )

            retrying = Retrying(
                stop=stop_after_attempt(normalized_attempts),
                retry=retry_if_exception_type(exception_types),
                wait=wait,
                reraise=True,
                before_sleep=lambda state: _log_state(state, "retry-before-sleep"),
            )

            for attempt in retrying:
                with attempt:
                    result = func(*args, **kwargs)
                _log_state(attempt.retry_state, "retry-success")
                return result

            raise RuntimeError("retry policy exited without executing function")

        return wrapper

    return decorator


@dataclass(slots=True)
class TimingHarness:
    """Deterministic timing controls aligned with Asia/Tehran timezone."""

    base: datetime
    step: float = 0.0005
    _perf_value: float = field(default=0.0)
    _current: datetime = field(init=False)

    def __post_init__(self) -> None:
        self._current = self.base

    def advance(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        self._current += timedelta(seconds=seconds)
        self._perf_value += seconds

    def perf_counter(self) -> float:
        self._perf_value += self.step
        return self._perf_value

    def epoch_seconds(self) -> float:
        return self._current.timestamp()

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


@pytest.fixture()
def timing_control(monkeypatch: pytest.MonkeyPatch) -> Iterator[TimingHarness]:
    """Provide deterministic replacements for timing functions during tests."""

    harness = TimingHarness(base=FREEZE_INSTANT)

    def _perf_counter() -> float:
        return harness.perf_counter()

    def _time() -> float:
        return harness.epoch_seconds()

    def _sleep(seconds: float) -> None:
        harness.sleep(seconds)

    monkeypatch.setattr(time, "perf_counter", _perf_counter)
    monkeypatch.setattr(time, "time", _time)
    monkeypatch.setattr(time, "sleep", _sleep)
    yield harness


@pytest.fixture()
def clean_redis_state_sync() -> Iterator[RedisNamespace]:
    """Synchronous wrapper ensuring Redis namespaces are isolated per test."""

    client = FakeStrictRedis()
    namespace = f"tests:{uuid.uuid4().hex}"
    client.flushdb()
    context = RedisNamespace(client=client, namespace=namespace)
    yield context
    leaked_keys = context.keys()
    client.flushdb()
    if leaked_keys:
        pytest.fail(
            f"کلیدهای ردیس پاک‌سازی نشدند: {sorted(leaked_keys)}",
            pytrace=False,
        )

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
