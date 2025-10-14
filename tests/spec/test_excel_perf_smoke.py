from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import pytest

from src.phase6_import_to_sabt.export_writer import ExportWriter
from src.phase6_import_to_sabt.sanitization import sanitize_text


@pytest.mark.perf
@pytest.mark.timeout(180)
def test_excel_export_perf_smoke(tmp_path: Path) -> None:
    if os.getenv("PERF", "0").lower() not in {"1", "true", "yes"}:
        pytest.skip("PERF=1 required for perf smoke")

    namespace = uuid4().hex
    output_path = tmp_path / f"export-{namespace}.xlsx"
    writer = ExportWriter(sensitive_columns=("national_id", "counter", "mobile", "mentor_id"))

    def _rows() -> Iterable[dict[str, str]]:
        risky = "=SUM(1,1)"
        for index in range(50_000):
            suffix = f"{namespace}-{index:05d}"
            yield {
                "national_id": f"'001234{suffix[:6]}",
                "counter": f"373{index:06d}",
                "first_name": risky,
                "last_name": sanitize_text(f"نام‌خانوادگی {suffix}"),
                "gender": "0",
                "mobile": f"0912{index:07d}"[-11:],
                "reg_center": "1",
                "reg_status": "1",
                "group_code": f"{index % 999:03d}",
                "student_type": "NORMAL",
                "school_code": f"{100000 + index}",
                "mentor_id": f"mentor-{suffix}",
                "mentor_name": sanitize_text(f"استاد {suffix}"),
                "mentor_mobile": f"0935{index:07d}"[-11:],
                "allocation_date": "1402-01-01",
                "year_code": "1402",
            }

    start = time.perf_counter()
    result = writer.write_xlsx(_rows(), path_factory=lambda _: output_path)
    duration = time.perf_counter() - start

    assert result.total_rows == 50_000, f"Rows mismatch: {result.total_rows}"
    assert output_path.exists(), "Output file missing"
    assert output_path.stat().st_size > 0, "Empty export file"
    assert not output_path.with_suffix(".xlsx.part").exists(), "Partial file left behind"

    with zipfile.ZipFile(output_path) as archive:
        shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
    assert "'=SUM(1,1)" in shared_strings or "&#39;=SUM(1,1)" in shared_strings

    context = {
        "duration_seconds": round(duration, 3),
        "size_bytes": output_path.stat().st_size,
        "rows": result.total_rows,
    }
    print(f"perf_context={context}")
