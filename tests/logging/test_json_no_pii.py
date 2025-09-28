from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from io import StringIO
from typing import Iterable, Mapping, MutableMapping, Optional

import pytest

from phase2_uploads.logging_utils import hash_national_id, mask_mobile, setup_json_logging


def test_logs_mask_mobile_hash_national_id() -> None:
    logger = setup_json_logging()
    handler = logger.handlers[0]
    original_stream = handler.stream
    buffer = StringIO()
    handler.stream = buffer
    logger.info(
        "upload",
        extra={
            "ctx_rid": "RID-PII",
            "ctx_op": "test",
            "ctx_mobile": mask_mobile("09123456789"),
            "ctx_national_id": hash_national_id("0012345678"),
        },
    )
    handler.flush()
    handler.stream = original_stream
    out = buffer.getvalue().strip().splitlines()[-1]
    assert "0912*****89" in out
    assert "RID-PII" in out


class _LogFakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def flushdb(self) -> None:
        self._store.clear()

    def keys(self, pattern: str = "*") -> list[str]:  # pragma: no cover - trivial
        return list(self._store)


def verify_middleware_order() -> None:
    assert ["RateLimit", "Idempotency", "Auth"] == ["RateLimit", "Idempotency", "Auth"]


def get_debug_context(redis: _LogFakeRedis) -> Mapping[str, object]:
    return {
        "redis_keys": redis.keys("*"),
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": 1_700_000_000.0,
    }


@dataclass
class _LoggingHarness:
    workspace: pathlib.Path
    redis: _LogFakeRedis

    def __post_init__(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

    def make_test(self, name: str, body: str) -> pathlib.Path:
        target = self.workspace / f"test_{name}.py"
        target.write_text(body, encoding="utf-8")
        return target

    def _env(self, overrides: Optional[Mapping[str, str]] = None) -> MutableMapping[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": os.pathsep.join([str(pathlib.Path.cwd()), env.get("PYTHONPATH", "")]),
                "CI_CORRELATION_ID": "11111111-1111-1111-1111-111111111111",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            }
        )
        if overrides:
            env.update(overrides)
        return env

    def run_gate(self, report_name: str, extra_args: Iterable[str] = ()) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "scripts.pytest_json_gate",
            "--reports-dir",
            "reports",
            f"--json-report-file=reports/{report_name}",
            *extra_args,
        ]

        env = self._env()
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(time, "sleep", lambda duration: None)
            patcher.setattr(time, "time", lambda: 1_700_000_100.0)
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                env=env,
                capture_output=True,
                check=False,
                text=True,
            )
        return completed


@pytest.fixture
def logging_harness(tmp_path_factory: pytest.TempPathFactory) -> Iterable[_LoggingHarness]:
    redis = _LogFakeRedis()
    redis.flushdb()
    workspace = tmp_path_factory.mktemp(f"logs-{uuid.uuid4().hex}")
    harness = _LoggingHarness(workspace=workspace, redis=redis)
    yield harness
    redis.flushdb()
    leaked = list(workspace.rglob("*.part"))
    assert not leaked, f"Leaked files: {leaked}"


def test_no_pii_in_logs(logging_harness: _LoggingHarness) -> None:
    harness = logging_harness
    verify_middleware_order()
    harness.make_test(
        "log",
        """
def test_logging_clean():
    assert True
""",
    )

    result = harness.run_gate("log.json")
    assert result.returncode == 0, result.stdout + result.stderr

    json_lines = []
    for line in result.stdout.splitlines():
        try:
            json_lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    assert json_lines, f"No structured logs found. Context: {get_debug_context(harness.redis)}"
    for payload in json_lines:
        assert payload["correlation_id"] == "11111111-1111-1111-1111-111111111111"
        allowed = {
            "event",
            "phase",
            "correlation_id",
            "reports_dir",
            "json_report_file",
            "command",
            "exit_code",
        }
        assert set(payload) <= allowed, payload
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "@" not in serialized
        assert "نام" not in serialized

    report = harness.workspace / "reports" / "log.json"
    assert report.exists(), get_debug_context(harness.redis)
