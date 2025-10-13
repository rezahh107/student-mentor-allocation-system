from __future__ import annotations

import pytest

from windows_launcher.launcher import Launcher, LauncherError


def test_p95_startup():
    launcher = Launcher()
    launcher._startup_samples.extend([2.0, 2.5, 1.5, 2.8])
    launcher.enforce_performance_budgets()

    launcher._startup_samples[:] = [9.1]
    with pytest.raises(LauncherError):
        launcher.enforce_performance_budgets()


def test_memory_budget(monkeypatch):
    launcher = Launcher()
    launcher.memory_budget_mb = 1.0
    monkeypatch.setattr("windows_launcher.launcher._current_memory_mb", lambda: 5.0)
    with pytest.raises(LauncherError):
        launcher.enforce_memory_budget()

