from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from freezegun import freeze_time

from scripts.deps.ensure_lock import (
    DependencyManager,
    PERSIAN_REQUIRE_HASHES_CONFLICT,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@freeze_time("2024-05-01T08:15:00+03:30")
@pytest.mark.evidence("Tailored v2.4 §2")
def test_constraints_only_requires_hash_override(monkeypatch, capsys) -> None:
    manager = DependencyManager(REPO_ROOT)
    monkeypatch.setenv("PIP_REQUIRE_HASHES", "1")
    monkeypatch.delenv("HASH_ENFORCED", raising=False)
    monkeypatch.setattr(manager, "_pip_tools_version", lambda: "7.5.1")
    def _fail(*args, **kwargs) -> None:
        pytest.fail("pip command should not execute when require-hashes conflict is detected")

    monkeypatch.setattr(manager, "_run_pip_command", _fail)
    with pytest.raises(SystemExit) as excinfo:
        manager.install()
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert PERSIAN_REQUIRE_HASHES_CONFLICT in err


@freeze_time("2024-05-01T08:15:00+03:30")
@pytest.mark.evidence("Tailored v2.4 §2")
def test_hash_enforced_switches_to_hashed_manifest(monkeypatch) -> None:
    manager = DependencyManager(REPO_ROOT)
    monkeypatch.setenv("PIP_REQUIRE_HASHES", "1")
    monkeypatch.setenv("HASH_ENFORCED", "1")
    monkeypatch.setattr(manager, "_pip_tools_version", lambda: "7.5.1")

    recorded: List[List[str]] = []

    def fake_run(cmd: List[str], **kwargs) -> None:
        recorded.append(cmd)

    monkeypatch.setattr(manager, "_run_pip_command", fake_run)
    monkeypatch.setattr(manager, "_post_install_validation", lambda constraints: None)
    monkeypatch.setattr(manager, "_write_install_marker", lambda **kwargs: None)
    monkeypatch.setattr(manager, "write_metrics", lambda: None)

    manager.install()

    assert recorded, "expected pip commands to be recorded"
    install_commands = [cmd for cmd in recorded if "pip" in cmd and "install" in cmd]
    hashed_invocations = [cmd for cmd in install_commands if "requirements-dev.txt" in " ".join(cmd)]
    assert hashed_invocations, f"expected hashed manifest usage; recorded={install_commands}"
    assert any("--require-hashes" in cmd for cmd in hashed_invocations), hashed_invocations
    editable_invocations = [cmd for cmd in install_commands if "--no-deps" in cmd and "-e" in cmd]
    assert editable_invocations, f"expected editable install after hashed phase; recorded={install_commands}"
