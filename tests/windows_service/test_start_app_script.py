from __future__ import annotations

from pathlib import Path


def test_start_app_script_invokes_controller_run():
    script = Path("Start-App.ps1").read_text(encoding="utf-8")
    assert "Import-DotEnv" in script
    assert "Ensure-RequiredEnv -Name 'DATABASE_URL'" in script
    assert "Ensure-RequiredEnv -Name 'REDIS_URL'" in script
    assert "Ensure-RequiredEnv -Name 'METRICS_TOKEN'" in script
    assert "Set-Item -Path Env:PYTHONPATH" in script
    assert "windows_service.readiness_cli" in script
    assert "app-stdout.log" in script
    assert "app-stderr.log" in script
    assert "windows_service.controller', 'run', '--port', $Env:SMASM_PORT" in script
    assert "25119" in script
    assert "READINESS_FAILED: «" in script
