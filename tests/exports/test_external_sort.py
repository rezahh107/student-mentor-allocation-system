from __future__ import annotations

from prometheus_client import CollectorRegistry

from phase6_import_to_sabt.external_sorter import ExternalSorter, SortPlan
from phase6_import_to_sabt.metrics import ExporterMetrics, reset_registry
from phase6_import_to_sabt.sanitization import sanitize_text


SORT_KEYS = ("year_code", "reg_center", "group_code", "school_code", "national_id")


def _build_row(index: int, *, year: int = 1402) -> dict[str, str | None]:
    school = "۱۲۳۴۵۶" if index % 2 else "000123"
    return {
        "year_code": str(year),
        "reg_center": str(index % 3),
        "group_code": str(200 - index),
        "school_code": school if index % 5 else None,
        "national_id": f"00{index:03d}",
        "first_name": "نام\u200c" + str(index),
        "last_name": "خانواده" + str(index),
    }


def test_spill_and_merge_stable_order(tmp_path) -> None:
    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)
    sorter = ExternalSorter(
        sort_keys=SORT_KEYS,
        buffer_rows=5,
        workspace_root=tmp_path / "sort",
        correlation_id="corr-sort",
        metrics=metrics,
    )
    rows = [_build_row(idx) for idx in range(1, 18)]
    plan: SortPlan | None = None
    try:
        plan = sorter.prepare(rows, format_label="csv")
        assert plan.total_rows == len(rows)
        assert plan.chunk_count >= 2
        materialized = list(sorter.iter_sorted(plan))
        keys = [
            _sort_key(snapshot)
            for snapshot in materialized
        ]
        assert keys == sorted(keys)
        assert all("\u200c" not in row["first_name"] for row in materialized)
        spill_samples = metrics.sort_spill_chunks_total.collect()[0].samples
        assert any(sample.labels.get("format") == "csv" and sample.value >= 1 for sample in spill_samples)
        rows_samples = metrics.sort_rows_total.collect()[0].samples
        assert any(sample.labels.get("format") == "csv" and sample.value == len(rows) for sample in rows_samples)
    finally:
        sorter.cleanup(plan)
        reset_registry(metrics.registry)


def _sort_key(row: dict[str, str]) -> tuple[str, int, int, int, str]:
    def to_int(value: str | None, default: int = 0) -> int:
        if value in (None, ""):
            return default
        return int(sanitize_text(str(value)))

    return (
        sanitize_text(str(row.get("year_code", ""))),
        to_int(row.get("reg_center")),
        to_int(row.get("group_code")),
        to_int(row.get("school_code"), default=999_999),
        sanitize_text(str(row.get("national_id", ""))),
    )
