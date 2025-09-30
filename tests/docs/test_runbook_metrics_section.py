from __future__ import annotations

from pathlib import Path


def test_metrics_names_present() -> None:
    content = Path("RUNBOOK.md").read_text(encoding="utf-8")
    assert "auth_retry_exhaustion_total" in content, f"Metric missing. Context: {content}"
    assert "auth_retry_backoff_seconds" in content, f"Histogram missing. Context: {content}"
    assert "DebugContext" in content, f"Debug guidance missing. Context: {content}"
