from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from multiprocessing import Process
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(name="clean_state")
def fixture_clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Ensure controller-required environment variables use unique namespaces."""
    unique = uuid4().hex
    overrides = {
        "DATABASE_URL": f"sqlite:///file:{unique}?mode=memory&cache=shared",
        "REDIS_URL": f"redis://127.0.0.1/0?namespace={unique}",
        "METRICS_TOKEN": f"metrics-{unique}",
        "PYTHONPATH": os.pathsep.join((str(PROJECT_ROOT / "src"), str(PROJECT_ROOT))),
    }
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)
    # Ensure launcher picks fake backend in CI contexts
    monkeypatch.setenv("FAKE_WEBVIEW", "1")
    yield overrides


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tester:
        tester.bind(("127.0.0.1", 0))
        return tester.getsockname()[1]


def _run_controller(port: int) -> None:
    os.environ.setdefault("STUDENT_MENTOR_APP_PORT", str(port))
    from windows_service.controller import _run_uvicorn

    _run_uvicorn(port)


def _wait_for_readyz(port: int, *, attempts: int = 40, timeout: float = 1.0) -> dict[str, object]:
    url = f"http://127.0.0.1:{port}/readyz"
    last_error: dict[str, object] | None = None
    base_delay = 0.1
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return {"status": response.status, "body": payload, "attempt": attempt}
        except urllib.error.URLError as exc:  # pragma: no cover - timing dependent
            reason = getattr(exc, "reason", exc)
            last_error = {"kind": "network", "reason": str(reason), "attempt": attempt}
        except urllib.error.HTTPError as exc:
            last_error = {"kind": "http", "status": exc.code, "reason": exc.reason, "attempt": attempt}
        delay = min(base_delay * (2 ** (attempt - 1)), 1.5)
        jitter = 0.03 * attempt
        time.sleep(delay + jitter)
    debug = {
        "url": url,
        "attempts": attempts,
        "last_error": last_error,
        "env": {k: os.getenv(k, "") for k in ["DATABASE_URL", "REDIS_URL", "METRICS_TOKEN"]},
        "timestamp": time.time(),
    }
    raise AssertionError(f"/readyz did not return 200: {debug}")


@pytest.mark.integration
@pytest.mark.timeout(30)
def test_readyz_local(clean_state: dict[str, str]) -> None:
    port = _allocate_port()
    process = Process(target=_run_controller, args=(port,), daemon=True)
    process.start()
    try:
        probe = _wait_for_readyz(port, attempts=60)
        assert probe["status"] == 200, f"Unexpected status: {probe}"
        assert probe["body"].get("status") == "ok"

        payload = json.dumps({"priority_mode": "balanced", "guarantee_assignment": False}).encode("utf-8")
        request = urllib.request.Request(
            url=f"http://127.0.0.1:{port}/api/v1/allocation/run",
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer token-ci",
                "Content-Type": "application/json",
                "Idempotency-Key": f"test-{uuid4().hex}",
            },
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            chain = response.headers.get("X-Middleware-Chain", "")
            assert chain == "RateLimit,Idempotency,Auth", f"middleware order mismatch: {chain}"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5)


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_launcher_prints_port_and_readyz(
    clean_state: dict[str, str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    port = _allocate_port()
    process = Process(target=_run_controller, args=(port,), daemon=True)
    process.start()
    try:
        monkeypatch.setenv("FAKE_WEBVIEW", "1")
        monkeypatch.setenv("STUDENT_MENTOR_APP_PORT", str(port))

        from windows_launcher import launcher as launcher_mod
        from windows_shared import config as ws_config

        launcher_config = ws_config.LauncherConfig(
            port=port,
            host="127.0.0.1",
            ui_path="/ui",
            version="test",
        )

        lock_token = uuid4().hex
        monkeypatch.setattr(ws_config, "lock_path", lambda: tmp_path / f"launcher-{lock_token}.lock")
        monkeypatch.setattr(ws_config, "load_launcher_config", lambda clock=None: launcher_config)
        monkeypatch.setattr(ws_config, "persist_launcher_config", lambda cfg, clock=None: None)
        monkeypatch.setattr(launcher_mod, "load_launcher_config", lambda clock=None: launcher_config)
        monkeypatch.setattr(launcher_mod, "persist_launcher_config", lambda cfg, clock=None: None)
        monkeypatch.setattr(launcher_mod, "_is_port_available", lambda host, port: True)

        launcher = launcher_mod.Launcher()
        exit_code = launcher.run()
        captured = capsys.readouterr()

        assert exit_code == 0, f"Launcher failed: exit={exit_code}, stderr={captured.err}"
        match = re.search(r"backend port: (?P<port>\d+)", captured.out)
        assert match is not None, f"Missing port output: {captured.out!r}"
        printed_port = int(match.group("port"))
        assert printed_port == port, f"Port mismatch: printed={printed_port}, expected={port}"

        probe = _wait_for_readyz(port, attempts=45, timeout=1.5)
        assert probe["status"] == 200, f"Readyz probe failed: {json.dumps(probe, ensure_ascii=False)}"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5)
