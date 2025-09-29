import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "path",
    [
        Path("ops/dashboards/slo.json"),
        Path("ops/dashboards/exports.json"),
        Path("ops/dashboards/uploads.json"),
        Path("ops/dashboards/errors.json"),
    ],
)
def test_dashboards_json_schema_ok(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "dashboard" in data, f"Missing dashboard key in {path}"
    dashboard = data["dashboard"]
    assert isinstance(dashboard.get("panels"), list)
    for panel in dashboard["panels"]:
        assert {"id", "title", "targets"}.issubset(panel.keys())
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            assert "{" in expr or "node" in expr, f"Expression too trivial: {expr}"
