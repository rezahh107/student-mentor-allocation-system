from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, make_row


def test_export_manifest_uses_injected_tehran_clock(tmp_path) -> None:
    base_time = datetime(2024, 3, 20, 12, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    rows = [make_row(idx=1), make_row(idx=2)]
    exporter = build_exporter(tmp_path, rows)
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv"),
        snapshot=ExportSnapshot(marker="ts", created_at=base_time),
        clock_now=base_time,
    )
    assert manifest.generated_at == base_time
    payload = json.loads((tmp_path / "export_manifest.json").read_text(encoding="utf-8"))
    assert payload["generated_at"] == base_time.isoformat()
