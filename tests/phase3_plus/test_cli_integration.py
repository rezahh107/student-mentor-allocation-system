from __future__ import annotations

import csv
from pathlib import Path

from scripts.phase3_cli import main as cli_main


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_cli_exports_safe_csv(tmp_path: Path) -> None:
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
        ["101", "0", "A|B", "0|1", "4", "1", "true", "NORMAL", "", "10", "0|1", ""],
        ["202", "0", "A|B", "0|1", "5", "2", "true", "SCHOOL", "300", "11", "0|1", "1402:300"],
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
        ["۱۲۳", "0", "A", "0", "0", "1", "", "0", ""],
        ["456", "0", "A", "0", "0", "1", "۳۰۰", "1", "1402"],
    ]
    _write_csv(students_path, student_headers, student_rows)

    output_path = tmp_path / "alloc.csv"
    exit_code = cli_main(
        [
            "--in",
            str(students_path),
            "--mentors",
            str(mentors_path),
            "--out",
            str(output_path),
            "--bom",
            "none",
            "--excel-safe",
            "true",
        ]
    )
    assert exit_code == 0

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert len(rows) == 2
    first = rows[0]
    assert first["student_id"] == "123"
    assert first["selected_mentor_id"] == "101"
    assert first["occupancy_ratio"] == "0.25"
    assert "GENDER_MATCH:1" in first["trace"]

    second = rows[1]
    assert second["selected_mentor_id"] == "202"
    assert second["student_id"] == "456"
    assert "SCHOOL_TYPE_COMPATIBLE:1" in second["trace"]
