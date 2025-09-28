from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ci_orchestrator.orchestrator import Orchestrator, OrchestratorConfig


def test_tehran_clock_injection(monkeypatch, tmp_path):
    class _FakeDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            base = dt.datetime(2024, 1, 1, 7, 0, tzinfo=dt.timezone.utc)
            return base.astimezone(tz)

    import ci_orchestrator.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "dt", dt)
    monkeypatch.setattr(orch_mod.dt, "datetime", _FakeDateTime)
    monkeypatch.setenv("TZ", "Asia/Tehran")
    config = OrchestratorConfig(
        phase="install",
        install_cmd=("echo", "install"),
        retries=1,
    )
    orchestrator = Orchestrator(config)
    instant = orchestrator._default_clock()
    assert instant.tzinfo == ZoneInfo("Asia/Tehran")
    assert instant.hour == 10
    env = orchestrator._build_env("default")
    assert env["TZ"] == "Asia/Tehran"
    assert env["PYTHONWARNINGS"] == "default"
