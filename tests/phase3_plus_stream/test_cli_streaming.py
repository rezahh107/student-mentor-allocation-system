import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from scripts.phase3_cli import main as cli_main
from src.tools.export_excel_safe import iter_rows


def _write_csv(path: Path, headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _build_basic_files(tmp_path: Path) -> tuple[Path, Path]:
    mentors_path = tmp_path / "mentors.csv"
    mentor_headers = [
        "mentor_id",
        "gender",
        "allowed_groups",
        "allowed_centers",
        "capacity",
        "current_load",
        "is_active",
        "mentor_type",
        "special_schools",
        "manager_id",
        "manager_centers",
        "special_school_years",
    ]
    mentor_rows = [
        ["10", "0", "A", "0", "2", "1", "true", "NORMAL", "", "", "", ""],
        ["20", "0", "A", "0", "2", "0", "true", "SCHOOL", "300", "", "", "1402:300"],
    ]
    _write_csv(mentors_path, mentor_headers, mentor_rows)

    students_path = tmp_path / "students.csv"
    student_headers = [
        "student_id",
        "gender",
        "group_code",
        "reg_center",
        "reg_status",
        "edu_status",
        "school_code",
        "student_type",
        "roster_year",
    ]
    student_rows = [
        ["100", "0", "A", "0", "0", "1", "", "0", ""],
        ["200", "0", "A", "0", "0", "1", "۳۰۰", "1", "1402"],
    ]
    _write_csv(students_path, student_headers, student_rows)
    return students_path, mentors_path


def test_cli_streams_rows_and_persists_json(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    students_path, mentors_path = _build_basic_files(tmp_path)
    telemetry_path = tmp_path / "metrics.json"
    export_path = tmp_path / "out.csv"
    captured: dict[str, Any] = {}

    def fake_export(self, rows: Iterable[Mapping[str, object]], handle, *, include_bom: bool, excel_safe: bool) -> None:  # type: ignore[override]
        captured["rows_type"] = type(rows)
        for _ in iter_rows(rows, headers=self.headers, excel_safe=excel_safe):
            handle.write("")

    monkeypatch.setattr("scripts.phase3_cli.ExcelSafeExporter.export", fake_export)

    exit_code = cli_main(
        [
            "--in",
            str(students_path),
            "--mentors",
            str(mentors_path),
            "--out",
            str(export_path),
            "--bom",
            "utf8",
            "--excel-safe",
            "true",
            "--telemetry-out",
            str(telemetry_path),
            "--ui",
            "text",
        ]
    )

    assert exit_code == 0
    assert "rows_type" in captured and "list" not in str(captured["rows_type"])

    stdout = capsys.readouterr().out
    assert "منتور" in stdout
    assert telemetry_path.exists()
    payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert "durations" in payload and payload["durations"]
    assert "counters" in payload


def test_cli_writes_csv_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    students_path, mentors_path = _build_basic_files(tmp_path)
    telemetry_path = tmp_path / "metrics.csv"
    export_path = tmp_path / "out.csv"

    exit_code = cli_main(
        [
            "--in",
            str(students_path),
            "--mentors",
            str(mentors_path),
            "--out",
            str(export_path),
            "--bom",
            "none",
            "--excel-safe",
            "true",
            "--telemetry-out",
            str(telemetry_path),
            "--telemetry-format",
            "csv",
        ]
    )

    assert exit_code == 0
    assert telemetry_path.exists()
    content = telemetry_path.read_text(encoding="utf-8")
    assert "label,count,p50_ms" in content
