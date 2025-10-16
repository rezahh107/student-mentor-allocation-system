from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from windows_service.errors import DependencyNotReady
from windows_service import readiness_cli


@pytest.fixture()
def registry() -> CollectorRegistry:
    return CollectorRegistry()


def test_run_check_emits_backoff(monkeypatch: pytest.MonkeyPatch, registry: CollectorRegistry):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    attempts: list[int] = []

    def fake_probe(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise DependencyNotReady(
                "سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند.",
                context={"failures": "redis"},
            )
        return {"postgres": {"status": "ok"}, "redis": {"status": "ok"}}

    sleeps: list[float] = []
    monkeypatch.setattr(readiness_cli, "probe_dependencies", fake_probe)
    monkeypatch.setattr(readiness_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(readiness_cli, "plan_backoff", lambda seed, attempts, base: [200] * attempts)

    result = readiness_cli.run_check(2, 100, 0.1, registry=registry)

    assert result["redis"]["status"] == "ok"
    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(0.2)
    retry_metric = registry.get_sample_value(
        "winsw_readiness_backoff_total", {"outcome": "retry"}
    )
    success_metric = registry.get_sample_value(
        "winsw_readiness_backoff_total", {"outcome": "success"}
    )
    assert retry_metric == pytest.approx(1)
    assert success_metric == pytest.approx(1)


def test_run_check_surfaces_failure(monkeypatch: pytest.MonkeyPatch, registry: CollectorRegistry):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    def always_fail(*args, **kwargs):
        raise DependencyNotReady(
            "سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند.",
            context={"failures": "postgres"},
        )

    sleeps: list[float] = []
    monkeypatch.setattr(readiness_cli, "probe_dependencies", always_fail)
    monkeypatch.setattr(readiness_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(readiness_cli, "plan_backoff", lambda seed, attempts, base: [150] * attempts)

    with pytest.raises(DependencyNotReady):
        readiness_cli.run_check(2, 150, 0.1, registry=registry)

    exhausted_metric = registry.get_sample_value(
        "winsw_readiness_backoff_total", {"outcome": "exhausted"}
    )
    assert exhausted_metric == pytest.approx(1)
