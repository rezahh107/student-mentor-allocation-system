from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone

import pytest

from src.phase6_import_to_sabt.data_source import InMemoryDataSource
from src.phase6_import_to_sabt.exporter import ImportToSabtExporter
from src.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from src.phase6_import_to_sabt.roster import InMemoryRoster
from tests.export.helpers import make_row
from tests.helpers.integration_context import IntegrationContext


_SAMPLE_COUNT = len(IntegrationContext().create_student_roster_dataset())


@pytest.mark.parametrize("record_index", range(_SAMPLE_COUNT))
def test_student_type_derivation_matches_roster(
    integration_context,
    tmp_path_factory: pytest.TempPathFactory,
    record_index: int,
):
    """Ensure derived student_type aligns with roster membership across edge cases."""

    integration_context.clear_state()
    samples = integration_context.create_student_roster_dataset()
    sample = samples[record_index]
    roster_mapping = {1402: {654321, 999999}, 1403: {222222}}
    roster = InMemoryRoster(roster_mapping)
    workspace = tmp_path_factory.mktemp(
        f"roster-{integration_context.namespace.replace(':', '-')}", numbered=True
    )

    try:
        row = make_row(
            idx=record_index + 100,
            year=sample["year"],
            school_code=sample["school_code"],
            gender=sample.get("gender", 0),
        )

        exporter = ImportToSabtExporter(
            data_source=InMemoryDataSource([row]),
            roster=roster,
            output_dir=workspace,
        )
        snapshot = ExportSnapshot(
            marker="integration",
            created_at=datetime(2023, 7, 1, tzinfo=timezone.utc),
        )
        filters = ExportFilters(year=sample["year"])
        options = ExportOptions(output_format="csv", excel_mode=False)

        measurement = integration_context.measure_operation(
            lambda: exporter.run(
                filters=filters,
                options=options,
                snapshot=snapshot,
                clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc),
            ),
            label="student_type_export",
        )

        manifest = measurement["result"]
        assert manifest.files[0].row_count == 1, integration_context.format_debug(
            "Export did not emit expected row",
            sample=sample,
            measurement=measurement,
        )

        csv_path = next(workspace.glob("*.csv"))
        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            exported_row = next(reader)

        assert exported_row["student_type"] == str(sample["expected_type"]), (
            integration_context.format_debug(
                "Derived student_type mismatch",
                sample=sample,
                exported=exported_row,
                duration=measurement["duration"],
            )
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
@pytest.mark.parametrize(
    "year, school_code, expected",
    [
        (1402, 654321, True),
        (1402, 111111, False),
        (1402, None, False),
        (1403, 654321, False),
        (1403, 222222, True),
    ],
)
def test_roster_special_cases(integration_context, year, school_code, expected):
    """Validate InMemoryRoster special membership via deterministic retries."""

    integration_context.clear_state()
    roster = InMemoryRoster({1402: {654321}, 1403: {222222}})

    result = integration_context.call_with_retry(
        lambda: roster.is_special(year, school_code),
        label="roster_is_special",
    )
    assert result is expected, integration_context.format_debug(
        "Roster special-case mismatch",
        year=year,
        school_code=school_code,
        expected=expected,
        actual=result,
    )
