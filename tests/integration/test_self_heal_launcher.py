from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Callable

import pytest
from prometheus_client import CollectorRegistry

from sma.core.clock import FrozenClock, try_zoneinfo
from sma.ops.self_heal import SelfHealConfig, SelfHealLauncher
from sma.ops.self_heal.launcher import ServiceProbeResult


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_PATH = REPO_ROOT / "راهنمای_جامع_راه_اندازی_و_اجرای_student_mentor_allocation_power_shell_7_windows.md"


@pytest.fixture()
def frozen_clock() -> FrozenClock:
    tzinfo = try_zoneinfo().tzinfo
    clock = FrozenClock(timezone=tzinfo)
    clock.set(datetime(2024, 1, 1, 0, 0, 0, tzinfo=tzinfo))
    return clock


@pytest.fixture()
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env.example").write_text(
        "IMPORT_TO_SABT_DATABASE__DSN=postgresql://user:pass@localhost:5432/db\n",
        encoding="utf-8",
    )
    agents_src = REPO_ROOT / "AGENTS.md"
    repo.joinpath("AGENTS.md").write_text(agents_src.read_text(encoding="utf-8"), encoding="utf-8")
    return repo


class FakeClient:
    def __init__(self, responses: dict[str, tuple[int, dict[str, str]]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str]) -> FakeResponse:
        self.calls.append(url)
        status, headers_map = self._responses[url]
        return FakeResponse(status, headers_map)

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


@pytest.fixture()
def mock_http_client(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, tuple[int, dict[str, str]]]], None]:
    def factory(responses: dict[str, tuple[int, dict[str, str]]]) -> None:
        def client_ctor(*_, **__) -> FakeClient:
            return FakeClient(responses)

        monkeypatch.setattr("sma.ops.self_heal.launcher.httpx.Client", client_ctor)

    return factory


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IMPORT_TO_SABT_AUTH__METRICS_TOKEN", raising=False)
    monkeypatch.delenv("IMPORT_TO_SABT_REDIS__DSN", raising=False)
    monkeypatch.delenv("IMPORT_TO_SABT_DATABASE__DSN", raising=False)


def _build_launcher(
    repo: Path,
    frozen_clock: FrozenClock,
    registry: CollectorRegistry,
) -> SelfHealLauncher:
    config = SelfHealConfig(
        repo_root=repo,
        runbook_path=RUNBOOK_PATH,
        reports_dir=repo / "reports",
    )
    return SelfHealLauncher(config=config, clock=frozen_clock, registry=registry)


def test_self_heal_flow(
    temp_repo: Path,
    frozen_clock: FrozenClock,
    mock_http_client,
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CollectorRegistry()
    mock_http_client(
        {
            "http://127.0.0.1:8000/health": (200, {}),
            "http://127.0.0.1:8000/docs": (200, {}),
            "http://127.0.0.1:8000/metrics": (200, {"X-MW-Trace": "rid|RateLimit>Idempotency>Auth"}),
        }
    )
    launcher = _build_launcher(temp_repo, frozen_clock, registry)
    executed_commands: list[str] = []

    def fake_run(command: str, *, section: str, env: dict[str, str]) -> bool:
        executed_commands.append(f"{section}:{command}")
        return True

    monkeypatch.setattr(launcher._command_runner, "run", fake_run)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        launcher,
        "_probe_redis",
        lambda: ServiceProbeResult(name="redis", healthy=True, details="mock"),
    )
    monkeypatch.setattr(
        launcher,
        "_probe_postgres",
        lambda: ServiceProbeResult(name="postgres", healthy=True, details="mock"),
    )
    spawned: list[str] = []

    def fake_spawn(command: str, *, env: dict[str, str]) -> bool:
        spawned.append(command)
        return True

    monkeypatch.setattr(launcher, "_spawn_process", fake_spawn)
    launcher._sleep = lambda _: None

    result = launcher.run()
    captured = capsys.readouterr()

    assert result.success
    assert result.errors == []
    assert not result.fix_counts
    assert "هیچ خطایی" in captured.out
    assert "خلاصهٔ اقدامات اصلاحی" in captured.out
    env_path = temp_repo / ".env"
    assert env_path.exists()
    env_bytes = env_path.read_bytes()
    assert b"\r\n" in env_bytes
    report_json = json.loads((temp_repo / "reports" / "selfheal-run.json").read_text(encoding="utf-8"))
    assert report_json["success"] is True
    assert report_json["fix_counts"] == []
    assert spawned and "--workers 1" in spawned[0]
    assert executed_commands
    retry_value = registry.get_sample_value("selfheal_retry_total", {"operation": "health"})
    assert retry_value is not None and retry_value >= 1
    assert os.environ["PYTHONUTF8"] == "1"
    five_d = (temp_repo / "reports" / "5d_plus_report.txt").read_text(encoding="utf-8")
    assert "AGENTS.md::8" in five_d
    log_text = (temp_repo / "reports" / "selfheal-run.log").read_text(encoding="utf-8")
    log_lines = [json.loads(line) for line in log_text.splitlines() if line.strip()]
    assert log_lines, "structured logs should exist"
    assert log_lines[-1]["event"] == "completion"
    assert log_lines[-1]["context"]["success"] == "True"
    correlation_ids = {entry["correlation_id"] for entry in log_lines}
    assert len(correlation_ids) == 1


def test_port_rotation_records_error(
    temp_repo: Path,
    frozen_clock: FrozenClock,
    mock_http_client,
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CollectorRegistry()
    mock_http_client(
        {
            "http://127.0.0.1:8000/health": (200, {}),
            "http://127.0.0.1:8000/docs": (200, {}),
            "http://127.0.0.1:8000/metrics": (200, {"X-MW-Trace": "rid|RateLimit>Idempotency>Auth"}),
            "http://127.0.0.1:8800/health": (200, {}),
            "http://127.0.0.1:8800/docs": (200, {}),
            "http://127.0.0.1:8800/metrics": (200, {"X-MW-Trace": "rid|RateLimit>Idempotency>Auth"}),
        }
    )
    launcher = _build_launcher(temp_repo, frozen_clock, registry)
    monkeypatch.setattr(launcher._command_runner, "run", lambda *_, **__: True)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        launcher,
        "_probe_redis",
        lambda: ServiceProbeResult(name="redis", healthy=True, details="mock"),
    )
    monkeypatch.setattr(
        launcher,
        "_probe_postgres",
        lambda: ServiceProbeResult(name="postgres", healthy=True, details="mock"),
    )
    monkeypatch.setattr(launcher, "_spawn_process", lambda *_, **__: True)
    launcher._sleep = lambda _: None
    sock = socket.socket()
    sock.bind(("127.0.0.1", 8000))
    sock.listen(1)
    try:
        result = launcher.run()
    finally:
        sock.close()
    assert result.port != 8000
    assert any(error.step == "انتخاب پورت" for error in result.errors)
    assert result.fix_counts.get("پورت پشتیبان استفاده شد.") == 1


def test_middleware_order_violation_records_error(
    temp_repo: Path,
    frozen_clock: FrozenClock,
    mock_http_client,
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CollectorRegistry()
    mock_http_client(
        {
            "http://127.0.0.1:8000/health": (200, {}),
            "http://127.0.0.1:8000/docs": (200, {}),
            "http://127.0.0.1:8000/metrics": (200, {"X-MW-Trace": "rid|RateLimit>Auth>Idempotency"}),
        }
    )
    launcher = _build_launcher(temp_repo, frozen_clock, registry)
    monkeypatch.setattr(launcher._command_runner, "run", lambda *_, **__: True)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        launcher,
        "_probe_redis",
        lambda: ServiceProbeResult(name="redis", healthy=True, details="mock"),
    )
    monkeypatch.setattr(
        launcher,
        "_probe_postgres",
        lambda: ServiceProbeResult(name="postgres", healthy=True, details="mock"),
    )
    monkeypatch.setattr(launcher, "_spawn_process", lambda *_, **__: True)
    launcher._sleep = lambda _: None
    result = launcher.run()
    assert not result.success
    assert any("ترتیب میان‌افزار" in error.message for error in result.errors)
    exhaustion = registry.get_sample_value("selfheal_exhaustion_total", {"operation": "health"})
    assert exhaustion is not None and exhaustion >= 1


def test_missing_agents_file_records_error(
    temp_repo: Path,
    frozen_clock: FrozenClock,
    mock_http_client,
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = CollectorRegistry()
    (temp_repo / "AGENTS.md").unlink()
    launcher = _build_launcher(temp_repo, frozen_clock, registry)
    monkeypatch.setattr(launcher._command_runner, "run", lambda *_, **__: True)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        launcher,
        "_probe_redis",
        lambda: ServiceProbeResult(name="redis", healthy=True, details="mock"),
    )
    monkeypatch.setattr(
        launcher,
        "_probe_postgres",
        lambda: ServiceProbeResult(name="postgres", healthy=True, details="mock"),
    )
    launcher._sleep = lambda _: None
    mock_http_client(
        {
            "http://127.0.0.1:8000/health": (200, {}),
            "http://127.0.0.1:8000/docs": (200, {}),
            "http://127.0.0.1:8000/metrics": (200, {"X-MW-Trace": "rid|RateLimit>Idempotency>Auth"}),
        }
    )
    result = launcher.run()
    captured = capsys.readouterr()
    missing_agents_message = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
    assert not result.success
    assert any(error.message == missing_agents_message for error in result.errors)
    assert missing_agents_message in captured.out
    report_json = json.loads((temp_repo / "reports" / "selfheal-run.json").read_text(encoding="utf-8"))
    assert report_json["errors"][0]["message"] == missing_agents_message
