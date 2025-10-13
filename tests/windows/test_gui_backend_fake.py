from __future__ import annotations

from datetime import datetime

from src.core.clock import FrozenClock, validate_timezone
from src.ops.retry import build_retry_metrics
from windows_launcher.launcher import FakeWebviewBackend, Launcher


def test_window_render_flow():
    tz = validate_timezone("Asia/Tehran")
    clock = FrozenClock(timezone=tz)
    clock.set(datetime(2024, 1, 1, 9, 0, tzinfo=tz))

    backend = FakeWebviewBackend()
    launcher = Launcher(
        clock=clock,
        webview_backend=backend,
        probe=lambda port, _: True,
        sleep=lambda seconds: clock.tick(seconds),
        retry_metrics=build_retry_metrics("launcher_test"),
    )
    launcher.memory_budget_mb = 512.0

    exit_code = launcher.run()
    assert exit_code == 0
    assert backend.started is True
    assert backend.created_windows
    assert backend.created_windows[0]["url"].startswith("http://127.0.0.1")
