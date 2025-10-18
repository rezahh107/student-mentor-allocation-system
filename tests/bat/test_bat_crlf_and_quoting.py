from __future__ import annotations

from repo_auditor_lite.__main__ import (
    build_install_requirements,
    build_quick_start,
    build_run_application,
)


def _assert_crlf(script: str) -> None:
    lines = script.split("\r\n")
    assert len(lines) > 1
    assert all("\n" not in line for line in lines)


def test_bat_outputs_use_crlf() -> None:
    for builder in (build_install_requirements, build_run_application, build_quick_start):
        script = builder()
        _assert_crlf(script)
        assert 'set "SCRIPT_DIR=%~dp0"' in script
        assert "@echo off" in script
