"""Strict parser integration tests with deterministic context."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import List

import pytest

PARSER = Path(__file__).resolve().parents[2] / "tools" / "ci" / "parse_pytest_summary.py"


@pytest.fixture
def clean_state(tmp_path, request):
    """Provide deterministic sandbox cleanup around parser invocations."""
    namespace = f"ci-parser-{request.node.name}"
    baseline_env = {key: os.environ.get(key) for key in list(os.environ.keys())}
    # pre-clean
    for key in list(os.environ.keys()):
        if key.startswith("CI_PARSER_TEST_"):
            os.environ.pop(key, None)
    yield {"namespace": namespace, "tmp": tmp_path}
    # post-clean
    for key in list(os.environ.keys()):
        if key not in baseline_env:
            os.environ.pop(key, None)
    for key, value in baseline_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _run_parser_with_retry(args: List[str], *, summary: str) -> subprocess.CompletedProcess[str]:
    """Run the strict parser with deterministic exponential backoff."""
    backoff_base = 0.01
    captured_error: List[str] = []
    for attempt in range(3):
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, str(PARSER), "--summary-text", summary, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        duration = time.perf_counter() - start
        if proc.returncode == 0:
            return proc
        captured_error.append(
            f"attempt={attempt + 1} rc={proc.returncode} duration={duration:.4f}s stderr={proc.stderr}"
        )
        jitter = 0.0  # deterministic no-op jitter
        delay = backoff_base * (2 ** attempt) + jitter
        time.sleep(delay)
    raise AssertionError(
        "\n".join(["strict parser failed"] + captured_error)
    )


def test_strict_parser_hits_perfect_score(clean_state: dict[str, object]) -> None:
    """Ensure Strict Scoring v2 emits 100/100 with clean summary and full evidence."""
    summary = textwrap.dedent(
        """
        === 3 passed, 0 failed in 0.12s ===
        === 0 skipped, 0 warnings ===
        """
    ).strip()
    evidence_args = [
        "--gui-out-of-scope",
        "--evidence",
        "AGENTS.md::2 Setup & Commands",
        "--evidence",
        "AGENTS.md::3 Absolute Guardrails",
        "--evidence",
        "AGENTS.md::8 Testing & CI Gates",
        "--evidence",
        "AGENTS.md::10 User-Visible Errors",
        "--fail-under",
        "100",
    ]
    result = _run_parser_with_retry(evidence_args, summary=summary)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "TOTAL: 100/100" in output, output
    assert "Reason for Cap (if any):\n- None" in output
    assert "AGENTS.md::2 Setup & Commands" in output
    assert "Reallocation Bonus: +15 (Perf +9, Excel +6)" in output
