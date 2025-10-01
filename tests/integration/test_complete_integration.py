from __future__ import annotations

from pathlib import Path


def test_all_features_integrated(integration_context, persian_dataset, temp_excel_dir):
    """Sanity-check Excel safety, roster datasets, and counter validation telemetry together."""

    integration_context.clear_state()

    safe_df = integration_context.ensure_excel_safety(
        persian_dataset,
        sensitive_columns=["نام"],
    )
    target_path = integration_context.generate_unique_path(temp_excel_dir, suffix=".xlsx")

    integration_context.call_with_retry(
        lambda: integration_context.write_dataframe_atomically(
            safe_df,
            target_path,
            format="xlsx",
        ),
        label="complete_excel",
    )

    assert Path(target_path).exists(), integration_context.format_debug(
        "Excel artifact missing after write",
        path=str(target_path),
    )

    roster_dataset = integration_context.create_student_roster_dataset()
    assert len(roster_dataset) >= 3, integration_context.format_debug(
        "Roster dataset unexpectedly small",
        roster_dataset=roster_dataset,
    )

    valid_example = "23{}{:04d}".format("373", 12)
    invalid_example = "invalid"

    assert integration_context.validate_counter_format(
        "sabt_counter",
        valid_example,
        gender_code=0,
    ), integration_context.format_debug(
        "Valid example counter rejected",
        value=valid_example,
    )
    assert not integration_context.validate_counter_format(
        "sabt_counter",
        invalid_example,
        gender_code=0,
    ), integration_context.format_debug(
        "Invalid example counter accepted",
        value=invalid_example,
    )

    telemetry = integration_context.telemetry
    assert telemetry["counter_validations"] == 2, integration_context.format_debug(
        "Telemetry counter_validations mismatch",
        telemetry=telemetry,
    )
    assert telemetry["valid_counters"] == 1, integration_context.format_debug(
        "Telemetry valid_counters mismatch",
        telemetry=telemetry,
    )

    Path(target_path).unlink(missing_ok=True)
