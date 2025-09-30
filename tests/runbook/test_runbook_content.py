from __future__ import annotations

from pathlib import Path


def test_runbook_content():
    text = Path("RUNBOOK.md").read_text(encoding="utf-8")
    assert "## sso-onboarding" in text
    assert "Go/No-Go" in text
    assert "blue" in text.lower()
