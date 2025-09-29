from __future__ import annotations

import os
from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_warnings() -> None:
    pytest_ini = _read(Path("pytest.ini"))
    assert "filterwarnings" in pytest_ini and "error" in pytest_ini, pytest_ini

    makefile = _read(Path("Makefile"))
    assert "PYTHONWARNINGS=error" in makefile, "Makefile must export PYTHONWARNINGS=error"

    orchestrator = _read(Path("tools/ci_test_orchestrator.py"))
    assert "env.setdefault(\"PYTHONWARNINGS\", \"error\")" in orchestrator

    env_value = os.environ.get("PYTHONWARNINGS", "error")
    assert env_value == "error", f"PYTHONWARNINGS expected 'error', got {env_value!r}"
