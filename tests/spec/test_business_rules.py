"""Business rule coverage for normalization, counters, and academic year codes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from src.phase2_counter_service.academic_year import AcademicYearProvider
from phase6_import_to_sabt.exceptions import ExportValidationError
from phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from phase6_import_to_sabt.models import (
    ExportFilters,
    ExportSnapshot,
    NormalizedStudentRow,
    SpecialSchoolsRoster,
)
from src.shared.counter_rules import COUNTER_REGEX, gender_prefix, validate_counter
from tests.fixtures.state import CleanupFixtures


class StubDataSource:
    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot) -> list[dict[str, object]]:  # pragma: no cover - interface stub
        del filters, snapshot
        return []


class StubRoster(SpecialSchoolsRoster):
    def __init__(self, specials: set[tuple[int, int | None]]) -> None:
        self._specials = specials

    def is_special(self, year: int, school_code: int | None) -> bool:  # type: ignore[override]
        return (year, school_code) in self._specials


@pytest.fixture(name="business_state")
def fixture_business_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


def _build_row(**overrides: object) -> NormalizedStudentRow:
    base = dict(
        national_id="0076543210",
        counter="143730001",
        first_name="علی",
        last_name="محمدی",
        gender=0,
        mobile="۰۹۱۲۳۴۵۶۷۸۹",
        reg_center=1,
        reg_status=3,
        group_code=42,
        student_type=0,
        school_code=123456,
        mentor_id="m-1",
        mentor_name="مربی",
        mentor_mobile="۰۹۰۱۲۳۴۵۶۷۸",
        allocation_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        year_code="1402",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        id=1,
    )
    base.update(overrides)
    return NormalizedStudentRow(**base)  # type: ignore[arg-type]


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_normalize_row_enforces_enums_and_student_type(tmp_path: Path, business_state: CleanupFixtures) -> None:
    roster = StubRoster({(1402, 123456)})
    exporter = ImportToSabtExporter(
        data_source=StubDataSource(),
        roster=roster,
        output_dir=tmp_path,
    )
    filters = ExportFilters(year=1402)
    row = _build_row()
    record = exporter._normalize_row(row, filters)
    context = business_state.context(record=record)
    assert record["reg_center"] in {"0", "1", "2"}, context
    assert record["reg_status"] in {"0", "1", "3"}, context
    assert record["student_type"] == "1", context
    assert record["mobile"].startswith("09"), context


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_normalize_row_rejects_invalid_center(tmp_path: Path, business_state: CleanupFixtures) -> None:
    roster = StubRoster(set())
    exporter = ImportToSabtExporter(
        data_source=StubDataSource(),
        roster=roster,
        output_dir=tmp_path,
    )
    filters = ExportFilters(year=1402)
    row = _build_row(reg_center=7)
    with pytest.raises(ExportValidationError) as exc_info:
        exporter._normalize_row(row, filters)
    context = business_state.context(error=str(exc_info.value))
    assert "reg_center" in str(exc_info.value), context


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_normalize_row_rejects_invalid_mobile(tmp_path: Path, business_state: CleanupFixtures) -> None:
    roster = StubRoster(set())
    exporter = ImportToSabtExporter(
        data_source=StubDataSource(),
        roster=roster,
        output_dir=tmp_path,
    )
    filters = ExportFilters(year=1402)
    row = _build_row(mobile="12345")
    with pytest.raises(ExportValidationError) as exc_info:
        exporter._normalize_row(row, filters)
    context = business_state.context(error=str(exc_info.value))
    assert "mobile" in str(exc_info.value), context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_counter_regex_and_gender_prefix(business_state: CleanupFixtures) -> None:
    value = "۱۴۳۷۳۳۳۳۳"
    normalized = validate_counter(value)
    context = business_state.context(normalized=normalized, regex=COUNTER_REGEX.pattern)
    assert COUNTER_REGEX.fullmatch(normalized), context
    assert normalized[2:5] == gender_prefix(0), context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_academic_year_provider_golden_cases(business_state: CleanupFixtures) -> None:
    mapping = {"۱۴۰۲": "۰۲", "1401": "01"}
    provider = AcademicYearProvider(mapping)
    codes = {
        "۱۴۰۲": provider.code_for("۱۴۰۲"),
        "1401": provider.code_for("۱۴۰۱"),
        "1399": provider.code_for("1399"),
    }
    context = business_state.context(codes=codes)
    assert codes["۱۴۰۲"] == "02", context
    assert codes["1401"] == "01", context
    assert codes["1399"] == "99", context
