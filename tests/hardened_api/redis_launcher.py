"""Developer-friendly Redis launcher for integration tests."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Callable, Iterator


LOGGER = logging.getLogger("tests.hardened_api.redis_launcher")


class RedisLaunchError(RuntimeError):
    """Raised when a developer Redis instance cannot be started."""


class RedisLaunchSkipped(RedisLaunchError):
    """Raised when Redis launch is intentionally skipped."""


@dataclass(slots=True)
class RedisRuntime:
    """Information about a running Redis instance."""

    url: str
    port: int
    process: subprocess.Popen[str] | None = None
    container_name: str | None = None
    mode: str = "external"

    def stop(self) -> None:
        if self.container_name:
            subprocess.run(
                ["docker", "stop", self.container_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if not self.process:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def _find_redis_binary() -> str:
    candidate = os.getenv("REDIS_SERVER_BINARY")
    if candidate:
        if os.path.exists(candidate):
            return candidate
        raise RedisLaunchError(f"Configured REDIS_SERVER_BINARY not found: {candidate}")
    for name in ("redis-server", "redis-server.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise RedisLaunchError(
        "redis-server binary not available. Install Redis or set REDIS_SERVER_BINARY to the executable path.",
    )


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _reserve_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_binary_process(binary: str, port: int) -> subprocess.Popen[str]:
    args = [
        binary,
        "--save",
        "",
        "--appendonly",
        "no",
        "--port",
        str(port),
        "--bind",
        "127.0.0.1",
    ]
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _launch_docker_container(container_name: str, port: int) -> str:
    image = os.getenv("REDIS_LAUNCHER_DOCKER_IMAGE", "redis:7-alpine")
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        container_name,
        "-p",
        f"127.0.0.1:{port}:6379",
        image,
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RedisLaunchError(
            f"docker run failed: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def _docker_is_running(container_name: str) -> bool:
    completed = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def _docker_failure_details(container_name: str) -> str:
    completed = subprocess.run(
        ["docker", "logs", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or completed.stderr.strip()


def _wait_for_ready(
    port: int,
    is_alive: Callable[[], bool],
    describe_failure: Callable[[], str],
    timeout: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_alive():
            raise RedisLaunchError(describe_failure())
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RedisLaunchError("Timed out waiting for redis-server to accept connections")


def _determine_mode() -> str:
    mode = os.getenv("REDIS_LAUNCH_MODE", "auto").strip().lower()
    if mode not in {"auto", "binary", "docker", "skip"}:
        raise RedisLaunchError(f"Unsupported REDIS_LAUNCH_MODE: {mode}")
    return mode


@contextlib.contextmanager
def launch_redis_server() -> Iterator[RedisRuntime]:
    """Start a disposable redis-server for local development tests."""

    env_url = os.getenv("REDIS_URL")
    if env_url:
        parsed = urllib.parse.urlparse(env_url)
        runtime = RedisRuntime(url=env_url, port=parsed.port or 6379, process=None, mode="external")
        LOGGER.info(
            "redis launcher using external url",
            extra={"redis_launch_mode": runtime.mode, "redis_url": runtime.url},
        )
        yield runtime
        return

    mode = _determine_mode()
    if mode == "skip":
        raise RedisLaunchSkipped("Redis launch skipped by REDIS_LAUNCH_MODE=skip")

    port = _reserve_port()
    runtime: RedisRuntime | None = None
    errors: list[str] = []

    if mode in {"auto", "binary"}:
        process: subprocess.Popen[str] | None = None
        try:
            binary = _find_redis_binary()
            process = _start_binary_process(binary, port)
            _wait_for_ready(
                port,
                is_alive=lambda: process.poll() is None,
                describe_failure=lambda: (process.stdout.read() if process.stdout else "redis-server exited"),
            )
            runtime = RedisRuntime(
                url=f"redis://127.0.0.1:{port}/0",
                port=port,
                process=process,
                container_name=None,
                mode="binary",
            )
        except RedisLaunchError as exc:
            errors.append(str(exc))
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if mode == "binary":
                raise

    if runtime is None and mode in {"auto", "docker"}:
        if not _docker_available():
            errors.append("docker cli unavailable")
        else:
            container_name = f"redis-test-{uuid.uuid4().hex}"
            try:
                _launch_docker_container(container_name, port)
                _wait_for_ready(
                    port,
                    is_alive=lambda: _docker_is_running(container_name),
                    describe_failure=lambda: _docker_failure_details(container_name),
                )
                runtime = RedisRuntime(
                    url=f"redis://127.0.0.1:{port}/0",
                    port=port,
                    process=None,
                    container_name=container_name,
                    mode="docker",
                )
            except RedisLaunchError as exc:
                errors.append(str(exc))
                subprocess.run(
                    ["docker", "stop", container_name],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if mode == "docker":
                    raise

    if runtime is None:
        if mode == "auto" and "docker cli unavailable" in errors:
            raise RedisLaunchSkipped(
                "redis-server binary missing and docker unavailable; set REDIS_LAUNCH_MODE=skip to bypass"
            )
        raise RedisLaunchError("Unable to launch redis-server: " + "; ".join(errors))

    LOGGER.info(
        "redis launcher ready",
        extra={
            "redis_launch_mode": runtime.mode,
            "redis_port": runtime.port,
            "redis_container": runtime.container_name,
        },
    )
    try:
        yield runtime
    finally:
        runtime.stop()


