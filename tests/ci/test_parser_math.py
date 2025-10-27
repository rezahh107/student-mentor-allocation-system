"""Validate Strict Scoring reallocation math stays deterministic."""
from __future__ import annotations

import textwrap

import pytest

from tests.ci import test_parser_strict as parser_strict

clean_state = parser_strict.clean_state
_run_parser_with_retry = parser_strict._run_parser_with_retry


@pytest.mark.usefixtures("clean_state")
def test_reallocation_bonus_totals_to_one_hundred(clean_state: dict[str, object]) -> None:
    """Ensure GUI reallocation bonus is surfaced and totals reach 100/100."""
    summary = textwrap.dedent(
        """
        === 3 passed, 0 failed, 0 skipped, 0 warnings ===
        """
    ).strip()
    args = [
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
    result = _run_parser_with_retry(args, summary=summary)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "Performance & Core: 40/40" in output
    assert "Persian Excel: 40/40" in output
    assert "GUI: 0/15" in output
    assert "Security: 5/5" in output
    assert "Reallocation Bonus: +15 (Perf +9, Excel +6)" in output
    assert "TOTAL: 100/100" in output
