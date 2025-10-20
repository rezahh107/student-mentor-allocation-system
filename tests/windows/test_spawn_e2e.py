from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pytest

from sma.phase6_import_to_sabt.sanitization import deterministic_jitter

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(name="clean_state")
def fixture_clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, str]]:
    """Isolate environment-dependent state for the spawned controller."""

    namespace = uuid4().hex
    python_path = os.pathsep.join((str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)))
    overrides = {
        "DATABASE_URL": f"sqlite:///file:{namespace}?mode=memory&cache=shared",
        "REDIS_URL": f"redis://127.0.0.1/0?namespace={namespace}",
        "METRICS_TOKEN": f"metrics-{namespace}",
        "PYTHONPATH": python_path,
        "TMPDIR": str(tmp_path / f"tmp-{namespace}"),
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("FAKE_WEBVIEW", "1")
    yield overrides


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tester:
        tester.bind(("127.0.0.1", 0))
        return tester.getsockname()[1]


def _wait_for_readyz(port: int, env: dict[str, str], *, attempts: int = 30) -> dict[str, object]:
    url = f"http://127.0.0.1:{port}/readyz"
    last_error: dict[str, object] | None = None
    seed = f"readyz:{port}:{env.get('METRICS_TOKEN', '')}"
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                body = json.loads(response.read().decode("utf-8"))
                return {"status": response.status, "body": body, "attempt": attempt}
        except urllib.error.HTTPError as exc:
            last_error = {
                "kind": "http",
                "status": exc.code,
                "reason": exc.reason,
                "attempt": attempt,
            }
        except urllib.error.URLError as exc:  # pragma: no cover - timing dependent
            last_error = {
                "kind": "network",
                "reason": str(getattr(exc, "reason", exc)),
                "attempt": attempt,
            }
        delay = min(deterministic_jitter(0.15, attempt, seed), 0.35)
        time.sleep(delay)
    debug = {
        "url": url,
        "attempts": attempts,
        "last_error": last_error,
        "env": {key: env.get(key, "") for key in ("DATABASE_URL", "REDIS_URL", "METRICS_TOKEN")},
        "timestamp": time.time(),
    }
    raise AssertionError(f"/readyz failed: {json.dumps(debug, ensure_ascii=False)}")


def _head_ui(port: int, *, attempts: int = 5) -> int:
    url = f"http://127.0.0.1:{port}/ui"
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            method="HEAD",
            headers={"Authorization": "Bearer smoke-ui"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 404}:
                return exc.code
            last_error = f"HTTP {exc.code} {exc.reason}"
        except urllib.error.URLError as exc:
            last_error = str(getattr(exc, "reason", exc))
        time.sleep(0.2 * attempt)
    raise AssertionError(f"UI HEAD failed: {url} last_error={last_error}")


@pytest.mark.integration
@pytest.mark.timeout(90)
def test_controller_spawn_end_to_end(clean_state: dict[str, str], tmp_path: Path) -> None:
    port = _allocate_port()
    env = os.environ.copy()
    env.update(clean_state)
    env["STUDENT_MENTOR_APP_PORT"] = str(port)

    log_dir = tmp_path / f"logs-{uuid4().hex}"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "controller.stdout.log"
    stderr_path = log_dir / "controller.stderr.log"

    command = [
        sys.executable,
        "-X",
        "dev",
        "-m",
        "windows_service.controller",
        "run",
        "--port",
        str(port),
    ]
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(  # noqa: S603 - deterministic command
            command,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        try:
            probe = _wait_for_readyz(port, env)
            assert probe["status"] == 200, f"Readiness unexpected: {json.dumps(probe, ensure_ascii=False)}"
            status = _head_ui(port)
            assert status == 200, (
                "UI HEAD mismatch: "
                + json.dumps(
                    {
                        "status": status,
                        "port": port,
                        "env": {key: env.get(key, "") for key in ("METRICS_TOKEN", "DATABASE_URL")},
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    stdout_text = stdout_path.read_text(encoding="utf-8")
    stderr_text = stderr_path.read_text(encoding="utf-8")
    acceptable_returns = {0, None, -signal.SIGTERM}
    if process.returncode not in acceptable_returns:
        tail = stderr_text.splitlines()[-10:]
        debug = {
            "returncode": process.returncode,
            "stderr_tail": tail,
            "stdout_tail": stdout_text.splitlines()[-10:],
            "port": port,
        }
        raise AssertionError(json.dumps(debug, ensure_ascii=False))

    if os.getenv("EXPECT_LAUNCHER_PORT_LINE"):
        assert "[StudentMentorApp] backend port:" in stdout_text, stdout_text
