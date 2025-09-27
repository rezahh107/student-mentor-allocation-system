from __future__ import annotations

import io
import pytest

from tests.hardened_api import redis_launcher
from tests.hardened_api.redis_launcher import RedisLaunchError, RedisLaunchSkipped, launch_redis_server


class DummyProcess:
    def __init__(self) -> None:
        self._alive = True
        self.stdout = io.StringIO("")

    def poll(self) -> int | None:  # pragma: no cover - signature parity
        return None if self._alive else 0

    def terminate(self) -> None:
        self._alive = False

    def wait(self, timeout: float | None = None) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


class DummyCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_launcher_prefers_binary(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_LAUNCH_MODE", "auto")
    monkeypatch.setattr(redis_launcher, "_reserve_port", lambda: 6390)
    monkeypatch.setattr(redis_launcher, "_find_redis_binary", lambda: "/usr/bin/redis-server")
    monkeypatch.setattr(redis_launcher, "_start_binary_process", lambda binary, port: DummyProcess())

    def fake_wait(port: int, is_alive, describe_failure, timeout: float = 10.0) -> None:
        assert is_alive()

    monkeypatch.setattr(redis_launcher, "_wait_for_ready", fake_wait)

    with caplog.at_level("INFO", logger="tests.hardened_api.redis_launcher"):
        with launch_redis_server() as runtime:
            assert runtime.mode == "binary", runtime
            assert runtime.container_name is None, runtime
    launch_records = [
        record for record in caplog.records if getattr(record, "redis_launch_mode", None)
    ]
    assert launch_records, "no redis launcher log captured"
    assert launch_records[-1].redis_launch_mode == "binary", launch_records[-1].__dict__


def test_launcher_falls_back_to_docker(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_LAUNCH_MODE", "auto")
    monkeypatch.setattr(redis_launcher, "_reserve_port", lambda: 6391)

    def raise_missing_binary() -> str:
        raise RedisLaunchError("binary missing")

    monkeypatch.setattr(redis_launcher, "_find_redis_binary", raise_missing_binary)
    monkeypatch.setattr(redis_launcher, "_docker_available", lambda: True)
    container_calls: dict[str, object] = {}

    def fake_launch(container_name: str, port: int) -> str:
        container_calls["name"] = container_name
        container_calls["port"] = port
        return "container-id"

    monkeypatch.setattr(redis_launcher, "_launch_docker_container", fake_launch)

    def fake_wait(port: int, is_alive, describe_failure, timeout: float = 10.0) -> None:
        assert port == 6391
        assert is_alive()

    monkeypatch.setattr(redis_launcher, "_wait_for_ready", fake_wait)
    monkeypatch.setattr(redis_launcher, "_docker_is_running", lambda name: True)
    monkeypatch.setattr(redis_launcher, "_docker_failure_details", lambda name: "")

    def fake_run(*args, **kwargs):
        cmd = args[0]
        if "inspect" in cmd:
            return DummyCompleted(stdout="true")
        if "stop" in cmd:
            return DummyCompleted()
        return DummyCompleted(stdout="container-id")

    monkeypatch.setattr(redis_launcher.subprocess, "run", fake_run)

    with caplog.at_level("INFO", logger="tests.hardened_api.redis_launcher"):
        with launch_redis_server() as runtime:
            assert runtime.mode == "docker", runtime
            assert runtime.container_name == container_calls["name"], container_calls
            assert container_calls["port"] == 6391, container_calls
    launch_records = [
        record for record in caplog.records if getattr(record, "redis_launch_mode", None)
    ]
    assert launch_records, "no redis launcher log captured"
    assert launch_records[-1].redis_launch_mode == "docker", launch_records[-1].__dict__


def test_launcher_skips_when_no_binary_or_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_LAUNCH_MODE", "auto")
    monkeypatch.setattr(redis_launcher, "_reserve_port", lambda: 6392)

    def raise_missing_binary() -> str:
        raise RedisLaunchError("binary missing")

    monkeypatch.setattr(redis_launcher, "_find_redis_binary", raise_missing_binary)
    monkeypatch.setattr(redis_launcher, "_docker_available", lambda: False)

    with pytest.raises(RedisLaunchSkipped):
        with launch_redis_server():
            pass


def test_launcher_honors_explicit_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_LAUNCH_MODE", "skip")

    with pytest.raises(RedisLaunchSkipped):
        with launch_redis_server():
            pass
