from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CLEAN_TARGETS: Sequence[str] = ("build", "dist", "*.egg-info", "pip-wheel-metadata")
_EVIDENCE_ANCHOR = "AGENTS.md::Determinism & CI"


@dataclass
class CommandResult:
    command: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    planned_backoff: List[float] = field(default_factory=list)


@dataclass
class PackagingState:
    root: Path
    env: Dict[str, str]
    namespace: str
    workspace: Path

    def run(self, command: Sequence[str], *, expect_success: bool) -> CommandResult:
        attempts: List[float] = []
        last_result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(3):
            planned_delay = _planned_delay(self.namespace, attempt)
            attempts.append(planned_delay)
            result = subprocess.run(
                command,
                cwd=self.root,
                env=self.env,
                text=True,
                capture_output=True,
                check=False,
            )
            last_result = result
            succeeded = result.returncode == 0
            if expect_success and succeeded:
                return CommandResult(command, result.returncode, result.stdout, result.stderr, attempts)
            if not expect_success and not succeeded:
                return CommandResult(command, result.returncode, result.stdout, result.stderr, attempts)
        debug_context = get_debug_context(self, last_result)
        raise AssertionError(
            f"Command did not reach expected state after retries. Context: {debug_context}"
        )

    def cleanup(self) -> None:
        _cleanup_targets(self.root)
        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)


def _cleanup_targets(root: Path) -> None:
    for pattern in _CLEAN_TARGETS:
        for item in root.glob(pattern):
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.exists():
                item.unlink(missing_ok=True)


def _planned_delay(namespace: str, attempt: int) -> float:
    seed = hashlib.blake2s(f"{namespace}:{attempt}".encode("utf-8"), digest_size=6).digest()
    jitter = int.from_bytes(seed, "big") % 1000 / 10000
    base = 0.05 * (2**attempt)
    return float(round(base + jitter, 4))


def get_debug_context(
    state: PackagingState,
    result: CommandResult | subprocess.CompletedProcess[str] | None,
) -> Dict[str, object]:
    return {
        "evidence": _EVIDENCE_ANCHOR,
        "namespace": state.namespace,
        "cwd": str(state.root),
        "planned_backoff": getattr(result, "planned_backoff", None),
        "last_returncode": getattr(result, "returncode", None),
        "stdout": getattr(result, "stdout", ""),
        "stderr": getattr(result, "stderr", ""),
        "env_snapshot": {
            key: state.env[key]
            for key in sorted({"PYTHONHASHSEED", "TZ", "SOURCE_DATE_EPOCH"} & state.env.keys())
        },
    }


@pytest.fixture
def packaging_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterable[PackagingState]:
    _cleanup_targets(PROJECT_ROOT)
    namespace = hashlib.blake2s(str(tmp_path).encode("utf-8"), digest_size=6).hexdigest()
    workspace = tmp_path / f"wheelhouse-{namespace}"
    workspace.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("TZ", "Asia/Tehran")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1704067200")
    env = dict(os.environ)
    state = PackagingState(root=PROJECT_ROOT, env=env, namespace=namespace, workspace=workspace)
    try:
        yield state
    finally:
        state.cleanup()
        _cleanup_targets(PROJECT_ROOT)
