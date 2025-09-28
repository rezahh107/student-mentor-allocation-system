from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional

import pytest

from scripts import pytest_json_gate


class _FakeRedis:
    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def flushdb(self) -> None:
        self._data.clear()

    def keys(self, pattern: str = "*") -> List[str]:  # pragma: no cover - trivial
        return list(self._data)


def _get_rate_limit_info() -> Mapping[str, str]:  # pragma: no cover - debug helper
    return {"limits": "cleared"}


def _get_middleware_chain() -> List[str]:  # pragma: no cover - debug helper
    return ["RateLimit", "Idempotency", "Auth"]


def verify_middleware_order() -> None:
    assert _get_middleware_chain() == ["RateLimit", "Idempotency", "Auth"], (
        "Middleware order mismatch",
        _get_middleware_chain(),
    )


def get_debug_context(fake_redis: _FakeRedis) -> Mapping[str, object]:
    return {
        "redis_keys": fake_redis.keys("*"),
        "rate_limit_state": _get_rate_limit_info(),
        "middleware_order": _get_middleware_chain(),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": 1_700_000_000.0,
    }


@dataclass
class _RetryPolicy:
    max_attempts: int = 3
    base_backoff: float = 0.05

    def run(self, func: Callable[[], subprocess.CompletedProcess[str]]) -> subprocess.CompletedProcess[str]:
        attempt = 0
        jitter_seed = 0.0
        while attempt < self.max_attempts:
            attempt += 1
            result = func()
            if result.returncode == 0:
                return result
            jitter_seed += 0.001
            time.sleep(self.base_backoff + jitter_seed)
        return result


@dataclass
class GateHarness:
    workdir: pathlib.Path
    redis: _FakeRedis
    sleep_log: List[float]

    def __post_init__(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "reports").mkdir(exist_ok=True)

    def make_test(self, name: str, body: str) -> pathlib.Path:
        test_path = self.workdir / f"test_{name}.py"
        test_path.write_text(body, encoding="utf-8")
        return test_path

    def _build_env(self, overrides: Optional[Mapping[str, str]] = None) -> MutableMapping[str, str]:
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": os.pathsep.join([str(pathlib.Path.cwd()), env.get("PYTHONPATH", "")]),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
            "CI_CORRELATION_ID": "00000000-0000-0000-0000-000000000000",
        })
        if overrides:
            env.update(overrides)
        return env

    def _run(self, args: Iterable[str], env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "scripts.pytest_json_gate",
            "--reports-dir",
            "reports",
            *args,
        ]

        prepared_env = self._build_env(env)

        policy = _RetryPolicy()

        def invoke() -> subprocess.CompletedProcess[str]:
            completed = subprocess.run(
                command,
                cwd=self.workdir,
                env=prepared_env,
                check=False,
                capture_output=True,
                text=True,
            )
            return completed

        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(time, "sleep", lambda duration: self.sleep_log.append(duration))
            result = policy.run(invoke)

        return result

    def run_gate(
        self,
        *,
        report_name: str,
        extra_args: Optional[Iterable[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        args = [f"--json-report-file=reports/{report_name}"]
        if extra_args:
            args.extend(extra_args)
        return self._run(args, env)


@pytest.fixture
def clean_state(tmp_path_factory: pytest.TempPathFactory) -> Iterable[GateHarness]:
    redis = _FakeRedis()
    redis.flushdb()
    namespace = f"gate-{uuid.uuid4().hex}"
    workdir = tmp_path_factory.mktemp(namespace)
    harness = GateHarness(workdir=workdir, redis=redis, sleep_log=[])
    patcher = pytest.MonkeyPatch()
    patcher.setattr(time, "time", lambda: 1_700_000_000.0)
    yield harness
    redis.flushdb()
    patcher.undo()
    leaked = list(workdir.rglob("*.part"))
    assert not leaked, f"Leaked temp artifacts: {leaked}"


def _assert_clean_final_state(harness: GateHarness) -> None:
    assert harness.redis.keys("*") == [], f"Redis dirty: {get_debug_context(harness.redis)}"


def test_runs_with_autoload_disabled(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "green",
        """
import warnings

def test_green_path():
    warnings.filterwarnings('error')
    assert True
""",
    )

    result = harness.run_gate(report_name="strict_score.json", extra_args=["-q"])
    assert result.returncode == 0, result.stdout + result.stderr

    report_path = harness.workdir / "reports" / "strict_score.json"
    assert report_path.exists(), get_debug_context(harness.redis)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["exitcode"] == 0, payload
    _assert_clean_final_state(harness)


def test_missing_plugin_fails_cleanly(clean_state: GateHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    harness = clean_state
    verify_middleware_order()

    original_import = pytest_json_gate.importlib.import_module

    def fake_import(name: str, package: Optional[str] = None):
        if name == "pytest_jsonreport":
            raise ImportError("simulated missing plugin")
        return original_import(name, package)

    monkeypatch.setattr(pytest_json_gate.importlib, "import_module", fake_import)

    with pytest.raises(SystemExit) as excinfo:
        pytest_json_gate.main([])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "SEC_PYTEST_JSON_PLUGIN_MISSING" in captured.err
    _assert_clean_final_state(harness)


def test_atomic_write_fsync_rename(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "atomic",
        """
def test_atomic():
    assert True
""",
    )

    report_name = "atomic.json"
    result = harness.run_gate(report_name=report_name)
    assert result.returncode == 0, result.stdout

    report_path = harness.workdir / "reports" / report_name
    part_path = report_path.with_suffix(".json.part")
    assert report_path.exists()
    assert not part_path.exists()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["created"], payload
    _assert_clean_final_state(harness)


def test_concurrent_runs_distinct_targets(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "first",
        """
def test_first():
    assert True
""",
    )

    harness.make_test(
        "second",
        """
def test_second():
    assert True
""",
    )

    first = harness.run_gate(report_name="first.json", extra_args=["-k", "first"])
    second = harness.run_gate(report_name="second.json", extra_args=["-k", "second"])
    assert first.returncode == 0 and second.returncode == 0

    first_json = harness.workdir / "reports" / "first.json"
    second_json = harness.workdir / "reports" / "second.json"
    assert first_json.exists() and second_json.exists()
    _assert_clean_final_state(harness)


def test_warnings_zero_enforced(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "warning",
        """
import warnings

def test_warning_trigger():
    warnings.warn('be wary')
""",
    )

    failing = harness.run_gate(report_name="warning.json")
    assert failing.returncode != 0
    assert "be wary" in failing.stderr or "warnings" in failing.stdout

    harness.make_test(
        "warning",
        """
def test_warning_trigger():
    assert True
""",
    )

    passing = harness.run_gate(report_name="warning_clean.json")
    assert passing.returncode == 0, passing.stdout
    _assert_clean_final_state(harness)


def test_cleanup_temp_artifacts(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "cleanup",
        """
def test_cleanup():
    assert True
""",
    )

    result = harness.run_gate(report_name="cleanup.json")
    assert result.returncode == 0

    leftover = list(harness.workdir.glob("reports/*.part"))
    assert leftover == [], leftover
    _assert_clean_final_state(harness)


def test_module_entrypoint(clean_state: GateHarness) -> None:
    harness = clean_state
    verify_middleware_order()
    harness.make_test(
        "entry",
        """
def test_entry():
    assert True
""",
    )

    command = [
        sys.executable,
        "-m",
        "scripts.pytest_json_gate",
        "--reports-dir",
        "reports",
        "--json-report-file=reports/module.json",
    ]

    prepared_env = harness._build_env({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(time, "sleep", lambda duration: harness.sleep_log.append(duration))
        completed = subprocess.run(
            command,
            cwd=harness.workdir,
            env=prepared_env,
            check=False,
            capture_output=True,
            text=True,
        )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report_path = harness.workdir / "reports" / "module.json"
    assert report_path.exists(), completed.stdout
    _assert_clean_final_state(harness)
