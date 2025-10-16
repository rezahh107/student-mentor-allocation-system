from __future__ import annotations

import socket
from collections import deque
import sys

import pytest
from prometheus_client import CollectorRegistry

from windows_service.errors import DependencyNotReady, ServiceError
from windows_service import readiness
from windows_service.readiness import plan_backoff, probe_dependencies


@pytest.fixture()
def registry() -> CollectorRegistry:
    return CollectorRegistry()


def test_backoff_deterministic(monkeypatch: pytest.MonkeyPatch):
    seed = "وابستگی"
    plan = plan_backoff(seed, attempts=4, base_ms=125)
    assert plan == [125, 227, 459, 987]


class DummySocket:
    def __init__(self, calls: list[tuple[tuple[str, int], float]]):
        self._calls = calls

    def __enter__(self) -> "DummySocket":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - nothing to clean
        return None


def test_probe_dependencies_success(monkeypatch: pytest.MonkeyPatch, registry: CollectorRegistry):
    calls: list[tuple[tuple[str, int], float]] = []
    monotonic_values = deque([1.0, 1.1, 2.0, 2.05])

    clients: list[FakeRedisClient] = []  # type: ignore[var-annotated]

    class FakeRedisClient:
        def __init__(self, url: str, socket_timeout: float | None = None) -> None:
            self.url = url
            self.socket_timeout = socket_timeout
            clients.append(self)

        def ping(self) -> bool:
            return True

        def close(self) -> None:  # pragma: no cover - defensive cleanup
            return None

    class FakeRedisModule:
        class Redis:  # type: ignore[too-few-public-methods]
            @staticmethod
            def from_url(url: str, socket_timeout: float | None = None) -> FakeRedisClient:
                return FakeRedisClient(url, socket_timeout)

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule())

    def fake_create_connection(address: tuple[str, int], timeout: float) -> DummySocket:
        calls.append((address, timeout))
        return DummySocket(calls)

    def fake_monotonic() -> float:
        return monotonic_values.popleft()

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(readiness.time, "monotonic", fake_monotonic)

    result = probe_dependencies(
        "postgresql://postgres:postgres@localhost:5432/postgres",
        "redis://localhost:6379/0",
        timeout_s=0.5,
        registry=registry,
    )

    assert result["postgres"]["status"] == "ok"
    assert result["redis"]["status"] == "ok"
    assert ("localhost", 5432) in [addr for addr, _ in calls]
    assert clients and clients[0].url == "redis://localhost:6379/0"

    postgres_attempts = registry.get_sample_value(
        "readiness_probe_attempts_total", {"dep": "postgres", "outcome": "success"}
    )
    redis_attempts = registry.get_sample_value(
        "readiness_probe_attempts_total", {"dep": "redis", "outcome": "success"}
    )
    assert postgres_attempts == pytest.approx(1)
    assert redis_attempts == pytest.approx(1)


def test_probe_dependencies_failure(monkeypatch: pytest.MonkeyPatch, registry: CollectorRegistry):
    monotonic_values = deque([1.0, 1.1, 2.0, 2.02])

    def fake_create_connection(address: tuple[str, int], timeout: float) -> DummySocket:
        host, port = address
        if port == 5432:
            return DummySocket([])
        raise ConnectionRefusedError(f"refused {host}:{port}")

    def fake_monotonic() -> float:
        return monotonic_values.popleft()

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(readiness.time, "monotonic", fake_monotonic)

    with pytest.raises(DependencyNotReady) as captured:
        probe_dependencies(
            "postgresql://postgres:postgres@localhost:5432/postgres",
            "redis://localhost:6380/0",
            timeout_s=0.2,
            registry=registry,
        )

    err = captured.value
    assert err.message == "سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند."
    assert err.context == {"failures": "redis"}

    failure_metric = registry.get_sample_value(
        "readiness_probe_failures_total", {"dep": "redis", "reason": "ConnectionRefusedError"}
    )
    if failure_metric is None:
        failure_metric = registry.get_sample_value(
            "readiness_probe_failures_total", {"dep": "redis", "reason": "ConnectionError"}
        )
    assert failure_metric == pytest.approx(1)


def test_probe_dependencies_missing_env(monkeypatch: pytest.MonkeyPatch, registry: CollectorRegistry):
    with pytest.raises(ServiceError) as captured:
        probe_dependencies("", "redis://localhost:6379/0", timeout_s=0.5, registry=registry)
    assert captured.value.code == "CONFIG_MISSING"
    assert captured.value.context == {"variable": "DATABASE_URL"}
