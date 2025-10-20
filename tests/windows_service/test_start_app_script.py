from __future__ import annotations

from pathlib import Path


def test_start_app_script_invokes_controller_run():
    script = Path("Start-App.ps1").read_text(encoding="utf-8")
    assert "Import-DotEnv" in script
    assert "Ensure-RequiredEnv -Name 'DATABASE_URL'" in script
    assert "Ensure-RequiredEnv -Name 'REDIS_URL'" in script
    assert "Ensure-RequiredEnv -Name 'METRICS_TOKEN'" in script
    assert "# Requires editable dev deps (AGENTS.md::8 Testing & CI Gates)" in script
    assert "python -m pip install -U pip setuptools wheel" in script
    assert "pip install -e .[dev] || pip install -e ." in script
    assert "Set-Item -Path Env:PYTHONPATH" not in script
    assert "windows_service.readiness_cli" in script
    assert "app-stdout.log" in script
    assert "app-stderr.log" in script
    assert "windows_service.controller', 'run', '--port', $Env:SMASM_PORT" in script
    assert "25119" in script
    assert "READINESS_FAILED: «" in script

    install_index = script.index("pip install -e .[dev]")
    run_index = script.index("windows_service.controller', 'run', '--port', $Env:SMASM_PORT")
    assert install_index < run_index, "باید قبل از راه‌اندازی سرویس، نصب editable اجرا شود."
