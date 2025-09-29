from __future__ import annotations

from pathlib import Path


def test_links_exist():
    doc = Path("docs/ops_metrics_map.md").read_text(encoding="utf-8")
    for dashboard in ("slo", "exports", "uploads", "errors"):
        assert f"ops/dashboards/{dashboard}.json" in doc
    assert "`export_duration_seconds" in doc
