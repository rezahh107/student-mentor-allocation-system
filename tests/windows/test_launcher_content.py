"""Validate Windows launcher artefacts stay aligned with documentation."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_state(request):
    """Provide deterministic namespace for launcher assertions."""
    namespace = f"launcher-{request.node.name}"
    start = time.perf_counter()
    yield {"namespace": namespace, "start": start}
    _ = time.perf_counter() - start  # ensure deterministic timing capture


def _assert_contains(content: str, patterns: Iterable[str]) -> None:
    debug_payload = {"remaining": list(patterns)}
    for pattern in patterns:
        if pattern not in content:
            raise AssertionError(f"missing pattern: {pattern}; context={debug_payload}")


def test_run_application_prefers_venv(clean_state: dict[str, object]) -> None:
    run_application = (REPO_ROOT / "run_application.bat").read_text(encoding="utf-8")
    expected_order = [
        ".venv\\Scripts\\python.exe",
        ".venv/bin/python",
        "set \"PYTHON_BIN=py\"",
        "if /I \"%PYTHON_BIN%\"==\"py\"",
        "-m uvicorn main:app",
    ]
    _assert_contains(run_application, expected_order)
    assert "chcp 65001" in run_application


def test_docs_anchor_windows_acceptance(clean_state: dict[str, object]) -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    section_snippets = [
        "## Windows Smoke & Acceptance",
        "findstr /s /n /i \"src.main:app\" *",
        "(Invoke-WebRequest -UseBasicParsing -Headers $H http://127.0.0.1:8000/metrics).StatusCode",
        "### 🧪 Windows Acceptance Checks",
        "uvicorn main:app --reload --host 0.0.0.0 --port 8000",
        "Determinism",
        "Windows Smoke",
    ]
    _assert_contains(agents, section_snippets[:3])
    _assert_contains(readme, section_snippets[3:])
    badge_pattern = re.compile(r"\[!\[Windows Smoke].+windows-smoke.yml")
    assert badge_pattern.search(readme), "missing Windows Smoke badge"
