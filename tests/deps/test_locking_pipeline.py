from __future__ import annotations

import json
import subprocess
import threading
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.deps.ensure_lock import (
    DependencyManager,
    PERSIAN_EXTRAS_CONFLICT,
    PERSIAN_LOCK_MISSING,
)


class StubProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _write_requirements(base: Path, *, duplicate: bool = False, extras: str | None = None) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "AGENTS.md").write_text("Middleware order: RateLimit → Idempotency → Auth", encoding="utf-8")
    runtime = ["fastapi==0.110.3"]
    if duplicate:
        runtime.append("fastapi==0.110.3")
    (base / "requirements.in").write_text("\n".join(runtime) + "\n", encoding="utf-8")
    dev_lines = ["-r requirements.in", "pytest==8.4.2"]
    if extras:
        dev_lines.append(extras)
    (base / "requirements-dev.in").write_text("\n".join(dev_lines) + "\n", encoding="utf-8")


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    return tmp_path / "deps"


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_verify_rejects_duplicate_pins(repo_root: Path) -> None:
    _write_requirements(repo_root, duplicate=True)
    manager = DependencyManager(repo_root)
    with pytest.raises(SystemExit) as exc:
        manager.verify()
    assert PERSIAN_LOCK_MISSING in str(exc.value)


@pytest.mark.evidence("AGENTS.md::Atomic I/O")
def test_lock_generates_metadata(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_requirements(repo_root)
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> StubProcess:
        commands.append(cmd)
        if "piptools" in cmd:
            Path(cmd[-2]).write_text("pytest==8.4.2\n", encoding="utf-8")
            return StubProcess(stdout="ok")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[arg-type]

    manager = DependencyManager(repo_root)
    manager.lock()

    assert (repo_root / "constraints.txt").read_text(encoding="utf-8").strip() == "pytest==8.4.2"
    meta = json.loads((repo_root / ".ci" / "constraints.txt.sha256").read_text(encoding="utf-8"))
    assert meta["constraint"] == "constraints.txt"
    assert "requirements.in" in meta["sources"]
    assert any("piptools" in cmd for cmd in commands)


@pytest.mark.evidence("CI/CD v2.4 §2 pip-tools")
def test_install_enforces_freeze(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_requirements(repo_root)
    (repo_root / "constraints-dev.txt").write_text("pytest==8.4.2\n", encoding="utf-8")
    (repo_root / "constraints.txt").write_text("fastapi==0.110.3\n", encoding="utf-8")
    manager = DependencyManager(repo_root)
    manager._write_metadata()

    executed: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> StubProcess:
        executed.append(cmd)
        if cmd[1:3] == ["-m", "pip"] and cmd[-2:] == ["pip", "wheel"]:
            return StubProcess(stdout="upgrade")
        if cmd[1:3] == ["-m", "pip"] and "freeze" in cmd:
            return StubProcess(stdout="pytest==8.4.2\n")
        if cmd[1:3] == ["-m", "pip"] and "check" in cmd:
            return StubProcess(stdout="")
        if cmd[1:3] == ["-m", "pip"] and "install" in cmd:
            assert "-c" in cmd
            assert str(repo_root / "constraints-dev.txt") in cmd
            assert str(repo_root / "requirements-dev.in") in cmd
            assert "-e" in cmd
            return StubProcess(stdout="install")
        if cmd[1:3] == ["-m", "pip"] and "upgrade" not in cmd and "install" not in cmd:
            return StubProcess(stdout="")
        return StubProcess(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[arg-type]

    manager = DependencyManager(repo_root)
    manager.install()

    commands = [" ".join(cmd) for cmd in executed]
    assert any("pip install -c" in cmd for cmd in commands)
    assert any("pip install -U pip wheel" in cmd for cmd in commands)
    marker = repo_root / "reports" / "ci-install.json"
    assert marker.exists()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["constraints"] == "constraints-dev.txt"
    assert payload["manifest"] == "requirements-dev.in"


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_verify_rejects_extras_conflict(repo_root: Path) -> None:
    _write_requirements(repo_root, extras="fastapi[all]>=0.111")
    manager = DependencyManager(repo_root)
    with pytest.raises(SystemExit) as exc:
        manager.verify()
    expected = PERSIAN_EXTRAS_CONFLICT.format(
        package="fastapi",
        base_source="requirements.in",
        extras_source="requirements-dev.in",
        base_spec="==0.110.3",
        extras_spec=">=0.111",
    )
    assert expected in str(exc.value)


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_verify_rejects_extras_shadowing_version(repo_root: Path) -> None:
    _write_requirements(repo_root, extras="fastapi[all]==0.110.3")
    manager = DependencyManager(repo_root)
    with pytest.raises(SystemExit) as exc:
        manager.verify()
    expected = PERSIAN_EXTRAS_CONFLICT.format(
        package="fastapi",
        base_source="requirements.in",
        extras_source="requirements-dev.in",
        base_spec="==0.110.3",
        extras_spec="==0.110.3",
    )
    assert expected in str(exc.value)


def test_verify_allows_versionless_extras(repo_root: Path) -> None:
    _write_requirements(repo_root, extras="fastapi[all]")
    manager = DependencyManager(repo_root)
    manager.validate_duplicates(manager.collect_requirements())


@pytest.mark.evidence("AGENTS.md::1 Project TL;DR")
def test_concurrent_lock_is_idempotent(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_requirements(repo_root)
    compile_calls: list[tuple[str, str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> StubProcess:
        if "piptools" in cmd:
            Path(cmd[-2]).write_text("pytest==8.4.2\n", encoding="utf-8")
            compile_calls.append((threading.current_thread().name, cmd[-1]))
            return StubProcess(stdout="compile")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[arg-type]

    barrier = threading.Barrier(2)

    def run_lock() -> None:
        barrier.wait()
        manager = DependencyManager(repo_root)
        manager.lock()

    threads = [threading.Thread(target=run_lock, name=f"lock-{idx}") for idx in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(compile_calls) == 2  # Only the first lock invocation runs pip-compile twice.
    assert (repo_root / ".ci" / "constraints.txt.sha256").exists()


@pytest.mark.evidence("Tailored v2.4 §2 pip-tools")
def test_requirements_txt_is_hashed_and_locked() -> None:
    project_root = Path(__file__).resolve().parents[2]
    content = (project_root / "requirements.txt").read_text(encoding="utf-8")
    dev_content = (project_root / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pip-compile" in content
    assert "pip-compile" in dev_content
    assert "--hash=" in content
    assert "--hash=" in dev_content
