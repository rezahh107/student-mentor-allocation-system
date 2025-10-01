from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psutil
import pytest

SENSITIVE_COLUMNS = ["national_id", "counter", "mobile", "mentor_id"]


def _normalize_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.replace("'", "", regex=False)


def test_large_file_export_performance(
    integration_context,
    large_dataset,
    temp_excel_dir,
):
    """Ensure 10k-row exports stay fast, atomic, and formula-safe."""

    integration_context.clear_state()
    safe_df = integration_context.ensure_excel_safety(
        large_dataset,
        sensitive_columns=SENSITIVE_COLUMNS,
    )
    assert safe_df[SENSITIVE_COLUMNS].apply(lambda col: col.str.startswith("'")).all().all()

    target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=".xlsx")

    measurement = integration_context.measure_operation(
        lambda: integration_context.call_with_retry(
            lambda: integration_context.write_dataframe_atomically(
                safe_df,
                target_path,
                format="xlsx",
            ),
            label="excel_export",
        ),
        label="excel_export",
    )
    stats = integration_context.file_stats(Path(target_path))

    assert measurement["duration"] <= 30.0, integration_context.format_debug(
        "Excel export exceeded 30s budget",
        duration=measurement["duration"],
        file_stats=stats,
    )
    assert 0 < stats["size_bytes"] < 50 * 1024 * 1024, integration_context.format_debug(
        "Excel export size outside expected bounds",
        file_stats=stats,
    )

    round_trip = pd.read_excel(target_path, engine="openpyxl")
    risky_cells = round_trip["formula_risk"].astype(str)
    assert risky_cells.str.startswith("=").sum() == 0, integration_context.format_debug(
        "Formula injection risk detected",
        risky_count=int(risky_cells.str.startswith("=").sum()),
    )
    ascii_digits = round_trip["mixed_digits"].astype(str)
    assert ascii_digits.str.contains("۰").sum() == 0, integration_context.format_debug(
        "Digit folding failed for mixed column",
        offending_values=ascii_digits[ascii_digits.str.contains("۰")].tolist(),
    )

    Path(target_path).unlink(missing_ok=True)


def test_persian_content_safety(
    integration_context,
    persian_dataset,
    temp_excel_dir,
):
    """Verify Persian content survives Excel round-trips with sanitisation."""

    integration_context.clear_state()
    safe_df = integration_context.ensure_excel_safety(
        persian_dataset,
        sensitive_columns=["نام", "مبلغ"],
    )
    target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=".xlsx")
    integration_context.call_with_retry(
        lambda: integration_context.write_dataframe_atomically(
            safe_df,
            target_path,
            format="xlsx",
        ),
        label="persian_excel",
    )

    round_trip = pd.read_excel(target_path, engine="openpyxl").fillna("")
    expected_names = _normalize_series(safe_df["نام"])
    actual_names = _normalize_series(round_trip["نام"])
    assert expected_names.tolist() == actual_names.tolist(), integration_context.format_debug(
        "Persian names changed after Excel export",
        expected=expected_names.tolist(),
        actual=actual_names.tolist(),
    )

    expected_sum = pd.to_numeric(_normalize_series(safe_df["مبلغ"]), errors="coerce").fillna(0).sum()
    actual_sum = pd.to_numeric(
        round_trip["مبلغ"].fillna(0).astype(str).str.replace("'", "", regex=False),
        errors="coerce",
    ).fillna(0).sum()
    assert expected_sum == actual_sum, integration_context.format_debug(
        "Persian monetary column mismatch",
        expected_sum=expected_sum,
        actual_sum=actual_sum,
    )

    assert (
        round_trip["یادداشت"].astype(str).str.contains("\u200c").sum() == 0
    ), integration_context.format_debug("Zero-width characters persisted", notes=round_trip["یادداشت"].tolist())

    Path(target_path).unlink(missing_ok=True)


def test_memory_usage_control(
    integration_context,
    large_dataset,
    temp_excel_dir,
):
    """Ensure chunked exports keep memory usage well below 500MB."""

    integration_context.clear_state()
    safe_df = integration_context.ensure_excel_safety(
        large_dataset,
        sensitive_columns=SENSITIVE_COLUMNS,
    )
    target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=".xlsx")

    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / (1024 * 1024)

    integration_context.call_with_retry(
        lambda: integration_context.write_excel_in_chunks(
            safe_df,
            target_path,
            chunk_size=1000,
        ),
        label="chunked_excel",
    )

    post_memory = process.memory_info().rss / (1024 * 1024)
    memory_increase = max(post_memory - initial_memory, 0)
    assert memory_increase < 500, integration_context.format_debug(
        "Chunked export exceeded memory budget",
        memory_increase=memory_increase,
        initial_memory=initial_memory,
        post_memory=post_memory,
    )

    Path(target_path).unlink(missing_ok=True)


@pytest.mark.parametrize("format_type", ["xlsx", "csv", "json"])
def test_export_format_safety(
    integration_context,
    large_dataset,
    temp_excel_dir,
    format_type,
):
    """Validate exporter resilience across supported formats with deterministic retries."""

    integration_context.clear_state()
    safe_df = integration_context.ensure_excel_safety(
        large_dataset.head(256),
        sensitive_columns=SENSITIVE_COLUMNS,
    )
    target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=f".{format_type}")

    def _export() -> Path:
        return integration_context.write_dataframe_atomically(
            safe_df,
            target_path,
            format=format_type,
        )

    integration_context.call_with_retry(_export, label=f"export_{format_type}")

    if format_type == "xlsx":
        round_trip = pd.read_excel(target_path, engine="openpyxl")
    elif format_type == "csv":
        round_trip = pd.read_csv(target_path, encoding="utf-8-sig")
    else:
        round_trip = pd.read_json(target_path, orient="records")

    assert len(round_trip) == len(safe_df), integration_context.format_debug(
        "Row count changed after export",
        format=format_type,
        expected=len(safe_df),
        actual=len(round_trip),
    )

    sensitive_snapshot = round_trip[[col for col in SENSITIVE_COLUMNS if col in round_trip.columns]]
    unsafe_mask = sensitive_snapshot.apply(lambda col: col.astype(str).str.startswith("=")).to_numpy()
    assert unsafe_mask.sum() == 0, integration_context.format_debug(
        "Sensitive column unsafe after export",
        format=format_type,
        snapshot=sensitive_snapshot.head().to_dict(orient="records"),
    )

    Path(target_path).unlink(missing_ok=True)
