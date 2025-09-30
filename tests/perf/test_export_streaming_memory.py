from __future__ import annotations

import tracemalloc

from src.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from src.phase6_import_to_sabt.xlsx.writer import XLSXStreamWriter


def _build_row(index: int) -> dict[str, object]:
    return {
        "national_id": f"{index:010d}",
        "counter": f"9900{index:06d}",
        "first_name": f"نام{index}",
        "last_name": f"خانواده{index}",
        "gender": index % 2,
        "mobile": f"0912{index:07d}"[-11:],
        "reg_center": index % 3,
        "reg_status": (index + 1) % 3,
        "group_code": index % 5,
        "student_type": index % 4,
        "school_code": f"{index % 1000:06d}",
        "mentor_id": f"{index:05d}",
        "mentor_name": f"راهنما{index}",
        "mentor_mobile": f"0935{index:07d}"[-11:],
        "allocation_date": "1402-01-01",
        "year_code": "02",
    }


def test_memory_under_cap(cleanup_fixtures) -> None:
    writer = XLSXStreamWriter(chunk_size=128)
    output_dir = cleanup_fixtures.base_dir / "perf"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "students.xlsx"
    metrics = build_import_export_metrics(cleanup_fixtures.registry)

    rows = [_build_row(i) for i in range(2048)]
    tracemalloc.start()
    writer.write(rows, output_path, metrics=metrics, format_label="xlsx", sleeper=lambda _: None)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    context = cleanup_fixtures.context(path=str(output_path))
    assert peak < 300 * 1024 * 1024, {
        "peak": peak,
        "current": current,
        "context": context,
    }
