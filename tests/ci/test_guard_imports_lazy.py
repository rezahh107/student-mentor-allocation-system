from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.evidence("AGENTS.md::6 Observability & Security")
@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_dependency_manager_lazy_imports(capsys) -> None:
    original_import = builtins.__import__

    def fake_import(name: str, globals: dict | None = None, locals: dict | None = None, fromlist=(), level: int = 0):
        if name.startswith("prometheus_client") or name.startswith("packaging"):
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    for module_name in list(sys.modules):
        if module_name.startswith("scripts.deps.ensure_lock"):
            sys.modules.pop(module_name)

    builtins.__import__ = fake_import
    try:
        ensure_lock = importlib.import_module("scripts.deps.ensure_lock")
        capsys.readouterr()  # clear import-time noise
        manager = ensure_lock.DependencyManager(REPO_ROOT)
        stderr = capsys.readouterr().err
        assert ensure_lock._format_guard_dependency("prometheus_client") in stderr
        with pytest.raises(SystemExit) as excinfo:
            manager.collect_requirements()
        assert excinfo.value.code == 2
        failure_err = capsys.readouterr().err
        assert ensure_lock._format_guard_dependency("packaging") in failure_err
    finally:
        builtins.__import__ = original_import
        for module_name in list(sys.modules):
            if module_name.startswith("scripts.deps.ensure_lock"):
                sys.modules.pop(module_name)
        importlib.import_module("scripts.deps.ensure_lock")
