"""Extended business rule coverage with Persian-specific assertions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from core.normalize import (
    GENDER_ERROR,
    MOBILE_ERROR,
    REG_STATUS_ERROR,
    normalize_gender,
    normalize_mobile,
    normalize_reg_status,
)
from phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from phase6_import_to_sabt.models import ExportFilters, NormalizedStudentRow, SpecialSchoolsRoster
from phase6_import_to_sabt.sanitization import sanitize_phone
from src.services.excel_import_service import ExcelImportService

from tests.fixtures.state import CleanupFixtures


class StubRoster(SpecialSchoolsRoster):
    def __init__(self, specials: set[tuple[int, int | None]]) -> None:
        self._specials = specials

    def is_special(self, year: int, school_code: int | None) -> bool:  # type: ignore[override]
        return (year, school_code) in self._specials


class StubDataSource:
    def fetch_rows(self, filters: ExportFilters, snapshot) -> list[dict[str, object]]:  # pragma: no cover - stub
        del filters, snapshot
        return []


def _build_row(**overrides: object) -> NormalizedStudentRow:
    base = dict(
        national_id="0076543210",
        counter="۱۴۳۷۳۰۰۰۱",
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
        year_code="۱۴۰۲",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        id=1,
    )
    base.update(overrides)
    return NormalizedStudentRow(**base)  # type: ignore[arg-type]


@pytest.fixture(name="business_extended_state")
def fixture_business_extended_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


@pytest.mark.integration
@pytest.mark.excel
def test_iranian_mobile_format_09xxxxxxxxx(business_extended_state: CleanupFixtures) -> None:
    """Normalize Persian/Arabic digits into the canonical 09XXXXXXXXX mobile pattern.

    Example:
        >>> normalize_mobile("۰۹١۲۳۴۵۶۷۸۹")
        '09123456789'
    """

    normalized = normalize_mobile("۰۹١۲۳۴۵۶۷۸۹")
    context = business_extended_state.context(normalized=normalized)
    assert normalized == "09123456789", context


@pytest.mark.integration
@pytest.mark.excel
def test_landline_format_with_area_code(business_extended_state: CleanupFixtures) -> None:
    """Sanitize landline numbers while preserving area codes in Persian error logs.

    Example:
        >>> sanitize_phone("۰۲۱-۴۴۴۴۵۵۵")
        '0214444555'
    """

    # Persian digits mixed with ASCII hyphen must fold without losing leading zeros.
    sanitized = sanitize_phone("۰۲۱-۴۴۴۴۵۵۵")
    context = business_extended_state.context(sanitized=sanitized)
    assert sanitized == "0214444555", context


@pytest.mark.integration
@pytest.mark.excel
def test_invalid_phone_rejection(business_extended_state: CleanupFixtures) -> None:
    """Invalid mobiles must raise deterministic Persian error messages.

    Example:
        >>> normalize_mobile("12345")
        Traceback (most recent call last):
            ...
        ValueError: شمارهٔ همراه باید با ۰۹ شروع شود و دقیقاً ۱۱ رقم باشد.
    """

    with pytest.raises(ValueError) as exc_info:
        normalize_mobile("12345")
    context = business_extended_state.context(error=str(exc_info.value))
    assert str(exc_info.value) == MOBILE_ERROR, context


@pytest.mark.integration
@pytest.mark.excel
def test_gender_enum_accepts_valid_only(business_extended_state: CleanupFixtures) -> None:
    """Gender normalization restricts accepted values to {0,1} with Persian errors.

    Example:
        >>> normalize_gender("زن"), normalize_gender("مرد")
        (0, 1)
    """

    context = business_extended_state.context()
    assert normalize_gender("زن") == 0
    assert normalize_gender("مرد") == 1
    with pytest.raises(ValueError) as exc_info:
        normalize_gender("unknown")
    assert str(exc_info.value) == GENDER_ERROR, context


@pytest.mark.integration
@pytest.mark.excel
def test_education_level_enum_validation(business_extended_state: CleanupFixtures) -> None:
    """Excel import rejects unsupported education statuses with Persian guidance.

    Example:
        >>> service = ExcelImportService()
        >>> service.validate_student_row([...], service.required_headers)  # doctest: +SKIP
    """

    service = ExcelImportService()
    headers = service.required_headers + ["نوع ثبت‌نام", "مرکز", "مقطع تحصیلی", "نوع مدرسه", "کد مدرسه"]
    row = [
        "علی",
        "محمدی",
        "1234567890",
        "09123456789",
        datetime(2005, 1, 1),
        "مرد",
        "نامشخص",  # invalid education status
        "عادی",
        "مرکز",
        "دبیرستان",
        "عادی",
        "123456",
    ]
    result = service.validate_student_row(row, headers)
    context = business_extended_state.context(errors=result.errors)
    assert not result.is_valid, context
    assert "وضعیت تحصیل نامعتبر است" in result.errors, context


@pytest.mark.integration
@pytest.mark.excel
def test_marital_status_enum_coverage(business_extended_state: CleanupFixtures) -> None:
    """Registration status enum mirrors marital status buckets in legacy exports.

    Example:
        >>> normalize_reg_status("حکمت")
        3
    """

    context = business_extended_state.context()
    assert normalize_reg_status(0) == 0
    assert normalize_reg_status("حکمت") == 3
    with pytest.raises(ValueError) as exc_info:
        normalize_reg_status("invalid")
    assert str(exc_info.value) == REG_STATUS_ERROR, context


@pytest.mark.integration
@pytest.mark.excel
def test_student_type_derived_from_special_schools_roster(tmp_path: Path, business_extended_state: CleanupFixtures) -> None:
    """Student type should flip to 1 when roster marks the school as special.

    Example:
        >>> exporter = ImportToSabtExporter(...)  # doctest: +SKIP
    """

    roster = StubRoster({(1402, 123456)})
    exporter = ImportToSabtExporter(data_source=StubDataSource(), roster=roster, output_dir=tmp_path)
    normalized = exporter._normalize_row(_build_row(), ExportFilters(year=1402))
    context = business_extended_state.context(normalized=normalized)
    assert normalized["student_type"] == "1", context


@pytest.mark.integration
@pytest.mark.excel
def test_derived_field_updates_on_source_change(tmp_path: Path, business_extended_state: CleanupFixtures) -> None:
    """Changing roster membership should recompute derived fields deterministically.

    Example:
        >>> roster = StubRoster({(1402, 123456)})
        >>> roster._specials.clear()
    """

    roster = StubRoster({(1402, 123456)})
    exporter = ImportToSabtExporter(data_source=StubDataSource(), roster=roster, output_dir=tmp_path)
    first_pass = exporter._normalize_row(_build_row(), ExportFilters(year=1402))
    # Remove school from special set to ensure derived field flips back to 0
    roster._specials.clear()
    second_pass = exporter._normalize_row(_build_row(), ExportFilters(year=1402))
    context = business_extended_state.context(first=first_pass["student_type"], second=second_pass["student_type"])
    assert first_pass["student_type"] == "1", context
    assert second_pass["student_type"] == "0", context
