from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from src.phase6_import_to_sabt.data_source import InMemoryDataSource
from src.phase6_import_to_sabt.exporter.csv_writer import normalize_cell
from src.phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from src.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot, NormalizedStudentRow
from src.phase6_import_to_sabt.roster import InMemoryRoster


def _row_with_variants() -> NormalizedStudentRow:
    return NormalizedStudentRow(
        national_id="۰۰۱۲۳۴۵۶۷۸",
        counter="993570001",
        first_name="ك\u200cریم",
        last_name="يگانه",
        gender=1,
        mobile="۰۹۱۲۳۴۵۶۷۸۹",
        reg_center=1,
        reg_status=3,
        group_code=77,
        student_type=0,
        school_code=654321,
        mentor_id="MN-01",
        mentor_name="=SUM(A1:A2)",
        mentor_mobile="۰۹۱۱۱۱۱۱۱۱۱",
        allocation_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        year_code="1403",
        created_at=datetime(2023, 12, 31, tzinfo=timezone.utc),
        id=99,
    )


def test_nfkc_digit_folding_and_char_unification():
    sample = " \u200cكلاس۱۲٣٤"
    normalized = normalize_cell(sample)
    assert normalized == "کلاس1234"


def test_domains_and_student_type_derivation(tmp_path: Path):
    roster = InMemoryRoster({1403: [654321]})
    data_source = InMemoryDataSource([_row_with_variants()])
    exporter = ImportToSabtExporter(data_source=data_source, roster=roster, output_dir=tmp_path)
    filters = ExportFilters(year=1403, center=1)
    snapshot = ExportSnapshot(marker="ci", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    options = ExportOptions(chunk_size=10, include_bom=False, excel_mode=True)

    manifest = exporter.run(
        filters=filters,
        options=options,
        snapshot=snapshot,
        clock_now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    export_file = tmp_path / manifest.files[0].name
    raw_content = export_file.read_text(encoding="utf-8-sig")

    assert "09123456789" in raw_content
    assert re.search(r"09\d{9}", raw_content)
    assert "reg_center" in raw_content and "reg_status" in raw_content

    normalized_row = exporter._normalize_row(_row_with_variants(), filters)  # type: ignore[attr-defined]
    assert normalized_row["reg_center"] in {"0", "1", "2"}
    assert normalized_row["reg_status"] in {"0", "1", "3"}
    assert normalized_row["student_type"] == "1"
    assert normalized_row["year_code"] == "1403"
    assert re.fullmatch(r"09\d{9}", normalized_row["mobile"])
