from __future__ import annotations

import csv
import json
import csv
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

from src.phase6_import_to_sabt.data_source import InMemoryDataSource
from src.phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from src.phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from src.phase6_import_to_sabt.metrics import ExporterMetrics
from src.phase6_import_to_sabt.models import (
    ExportFilters,
    ExportOptions,
    ExportSnapshot,
    NormalizedStudentRow,
)
from src.phase6_import_to_sabt.roster import InMemoryRoster
from src.tools.export.xlsx_exporter import XLSXAllocationExporter


def _build_row(**overrides) -> NormalizedStudentRow:
    base = dict(
        national_id="1234567890",
        counter="013730001",
        first_name="=SUM(A1:A2)",
        last_name="کاربر",
        gender=0,
        mobile="09123456789",
        reg_center=1,
        reg_status=1,
        group_code=42,
        student_type=0,
        school_code=123456,
        mentor_id="M-001",
        mentor_name="=cmd()",
        mentor_mobile="09112223344",
        allocation_date=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc),
        year_code="1403",
        created_at=datetime(2023, 12, 31, 8, 0, tzinfo=timezone.utc),
        id=1,
    )
    base.update(overrides)
    return NormalizedStudentRow(**base)


def test_sensitive_columns_are_always_quoted(tmp_path: Path):
    destination = tmp_path / "quoted.csv"
    rows = [
        {"national_id": "0012345678", "counter": "013730099", "value": "۱۲۳"},
    ]
    write_csv_atomic(
        destination,
        rows,
        header=["national_id", "counter", "value"],
        sensitive_fields=["national_id", "counter"],
        include_bom=False,
    )
    payload = destination.read_text(encoding="utf-8")
    data_line = payload.splitlines()[1]
    assert '"0012345678"' in data_line and '"013730099"' in data_line, payload


def test_csv_formula_values_are_guarded(tmp_path: Path):
    destination = tmp_path / "formulas.csv"
    rows = [
        ["=SUM(A1:A2)", "+99", "متن"],
    ]
    write_csv_atomic(
        destination,
        rows,
        header=["first_name", "counter", "note"],
        sensitive_fields=[0, 1],
        include_bom=False,
    )
    with destination.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader)
        row = next(reader)
    assert row[0].startswith("'"), row
    assert row[1].startswith("'"), row


def test_formula_values_guarded_in_excel_mode(tmp_path: Path):
    roster = InMemoryRoster({1403: [123456]})
    data_source = InMemoryDataSource([_build_row()])
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=tmp_path,
    )
    filters = ExportFilters(year=1403, center=1)
    snapshot = ExportSnapshot(marker="ci", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    options = ExportOptions(chunk_size=10, include_bom=True, excel_mode=True)
    manifest = exporter.run(
        filters=filters,
        options=options,
        snapshot=snapshot,
        clock_now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    assert manifest.files, "Export manifest should include files"
    export_file = tmp_path / manifest.files[0].name
    with export_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
    assert row["first_name"].startswith("'"), row
    assert row["mentor_name"].startswith("'"), row


def test_xlsx_sensitive_cells_written_as_text(tmp_path: Path):
    exporter = XLSXAllocationExporter()

    class _Record:
        allocation_id = 1
        allocation_code = "=SUM(A1:A2)"
        year_code = "1403"
        student_id = "0012345678"
        mentor_id = "M-01"
        status = "ACTIVE"
        policy_code = None
        created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def yield_per(self, _chunk):
            for row in self._rows:
                yield row

    class _Session:
        def __init__(self, record):
            self._record = record

        def execute(self, _stmt):
            return _Result([(self._record,)])

    destination = tmp_path / "allocations.xlsx"
    session = _Session(_Record())
    exporter.export(session=session, output=destination)

    workbook = openpyxl.load_workbook(destination, read_only=True)
    sheet = workbook.active
    cells = next(sheet.iter_rows(min_row=2, max_row=2, values_only=False))
    assert isinstance(cells[1].value, str) and cells[1].value.startswith("'"), cells
    assert cells[3].data_type == "s"


def test_finalize_and_manifest(tmp_path: Path):
    roster = InMemoryRoster({1403: [123456]})
    data_source = InMemoryDataSource([_build_row(counter="013730777", id=7)])
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=tmp_path,
    )
    filters = ExportFilters(year=1403, center=None)
    snapshot = ExportSnapshot(marker="ci", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    options = ExportOptions(chunk_size=1, include_bom=False, excel_mode=True)
    manifest = exporter.run(
        filters=filters,
        options=options,
        snapshot=snapshot,
        clock_now=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    partials = list(tmp_path.glob("*.part"))
    context = {"files": [p.name for p in tmp_path.iterdir()], "partials": [p.name for p in partials]}
    assert not partials, json.dumps(context, ensure_ascii=False)
    manifest_path = tmp_path / f"manifest_{manifest.profile.full_name}_{manifest.metadata['timestamp']}.json"
    assert manifest_path.exists(), json.dumps(context, ensure_ascii=False)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload.get("files"), payload


def test_metrics_include_format_label():
    metrics = ExporterMetrics()
    metrics.observe_rows(10, format="csv")
    metrics.observe_file_bytes(2048, format="csv")
    row_samples = metrics.rows_total.collect()[0].samples
    byte_samples = metrics.file_bytes_total.collect()[0].samples
    assert any(sample.labels.get("format") == "csv" for sample in row_samples)
    assert any(sample.labels.get("format") == "csv" for sample in byte_samples)
