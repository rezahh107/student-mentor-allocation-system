from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from src.core.clock import FrozenClock
from src.core.retry import RetryPolicy, build_sync_clock_sleeper, execute_with_retry
from windows_launcher import launcher as launcher_mod

_TEHRAN_TZ = ZoneInfo("Asia/Tehran")


@pytest.fixture
def gui_state(tmp_path, monkeypatch):
    namespace = f"gui:{uuid4().hex}"
    config_dir = tmp_path / namespace
    monkeypatch.setenv("STUDENT_MENTOR_APP_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("FAKE_WEBVIEW", "1")
    monkeypatch.setenv("STUDENT_MENTOR_APP_MACHINE_ID", namespace)
    yield config_dir
    monkeypatch.delenv("STUDENT_MENTOR_APP_CONFIG_DIR", raising=False)
    monkeypatch.delenv("FAKE_WEBVIEW", raising=False)
    monkeypatch.delenv("STUDENT_MENTOR_APP_MACHINE_ID", raising=False)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    clock = FrozenClock(timezone=_TEHRAN_TZ)
    clock.set(datetime(2024, 1, 1, tzinfo=_TEHRAN_TZ))
    return clock


@pytest.fixture
def gui_retry(frozen_clock: FrozenClock) -> Callable[[str, Callable[[], int]], int]:
    policy = RetryPolicy(base_delay=0.01, factor=2.0, max_delay=0.2, max_attempts=3)
    sleeper = build_sync_clock_sleeper(frozen_clock)

    def _run(label: str, func: Callable[[], int]) -> int:
        correlation = f"gui:{label}:{uuid4().hex}"
        return execute_with_retry(
            func,
            policy=policy,
            clock=frozen_clock,
            sleeper=sleeper,
            retryable=(Exception,),
            correlation_id=correlation,
            op=label,
        )

    return _run


@pytest.mark.gui
@pytest.mark.performance
def test_rtl_text_rendering(gui_state: Path, frozen_clock: FrozenClock, gui_retry, monkeypatch) -> None:
    backend = launcher_mod.FakeWebviewBackend()
    launcher = launcher_mod.Launcher(clock=frozen_clock, webview_backend=backend)
    launcher.retry_metrics = launcher_mod.build_retry_metrics("launcher-test")
    launcher.probe = lambda port, cid: True
    launcher.backend_launcher = lambda port: None
    launcher.enforce_memory_budget = lambda: None  # type: ignore[assignment]
    launcher.enforce_performance_budgets = lambda: None  # type: ignore[assignment]
    launcher._ensure_backend_started = lambda config, corr_id: None  # type: ignore[assignment]

    config = launcher_mod.LauncherConfig(port=launcher_mod.compute_port(), ui_path="/رابط?جهت=rtl")
    monkeypatch.setattr(launcher_mod, "ensure_agents_manifest", lambda start=None, max_depth=6: Path("AGENTS.md"))
    monkeypatch.setattr(launcher_mod, "load_launcher_config", lambda clock=None: config)
    monkeypatch.setattr(launcher_mod, "wait_for_backend", lambda *args, **kwargs: None)

    exit_code = gui_retry("launcher_run", launcher.run)
    assert exit_code == 0, json.dumps({"context": "launcher_run", "env": dict(backend=backend.__dict__)}, ensure_ascii=False)
    assert backend.started is True
    assert backend.created_windows, "هیچ پنجره‌ای برای وب‌ویو ایجاد نشد"
    window = backend.created_windows[-1]
    assert window["title"].startswith("سامانه"), window
    assert window["kwargs"].get("text_select") is True, window
    assert window["kwargs"].get("width") == 1280, window
    assert window["url"].startswith("http://127.0.0.1"), window
    assert "rtl" in window["url"], window


@pytest.mark.gui
def test_fake_webview_flag_detection(monkeypatch) -> None:
    monkeypatch.setenv("FAKE_WEBVIEW", "1")
    try:
        assert launcher_mod._should_use_fake_backend() is True
    finally:
        monkeypatch.setenv("FAKE_WEBVIEW", "0")
        assert launcher_mod._should_use_fake_backend() is False
        monkeypatch.delenv("FAKE_WEBVIEW", raising=False)
