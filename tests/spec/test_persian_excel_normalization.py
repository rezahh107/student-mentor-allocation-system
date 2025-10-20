"""High-risk Persian Excel normalization scenarios with deterministic hygiene."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from sma.phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from sma.phase6_import_to_sabt.models import (
    ExportFilters,
    NormalizedStudentRow,
    SpecialSchoolsRoster,
)
from sma.phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text, secure_digest
from sma.phase6_import_to_sabt.xlsx.utils import iter_chunks

from tests.fixtures.state import CleanupFixtures


class StubDataSource:
    def fetch_rows(self, filters: ExportFilters, snapshot) -> list[dict[str, object]]:  # pragma: no cover - stub
        del filters, snapshot
        return []


class StubRoster(SpecialSchoolsRoster):
    """Minimal roster that allows toggling of special schools per year."""

    def __init__(self, specials: set[tuple[int, int | None]]) -> None:
        self._specials = specials

    def is_special(self, year: int, school_code: int | None) -> bool:  # type: ignore[override]
        return (year, school_code) in self._specials


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


@pytest.fixture(name="excel_state")
def fixture_excel_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    """Flush Redis/metrics state before and after each Excel normalization test."""

    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


@pytest.mark.integration
@pytest.mark.excel
def test_null_values_in_required_fields(tmp_path: Path, excel_state: CleanupFixtures) -> None:
    """None values should normalize to safe empty strings for required columns.

    Example:
        >>> sanitize_text(None)
        ''
    """

    roster = StubRoster({(1402, 123456)})
    exporter = ImportToSabtExporter(
        data_source=StubDataSource(),
        roster=roster,
        output_dir=tmp_path,
    )
    row = _build_row(first_name=None, last_name=None)
    normalized = exporter._normalize_row(row, ExportFilters(year=1402))
    context = excel_state.context(normalized=normalized)
    assert normalized["first_name"] == "", context
    assert normalized["last_name"] == "", context


@pytest.mark.integration
@pytest.mark.excel
def test_none_vs_empty_string_distinction(excel_state: CleanupFixtures) -> None:
    """Demonstrate deterministic handling of None versus explicit blanks.

    Example:
        >>> sanitize_text(None), sanitize_text("")
        ('', '')
    """

    values = {
        "none": sanitize_text(None),
        "empty": sanitize_text(""),
        "space": sanitize_text(" "),
    }
    context = excel_state.context(values=values)
    assert values["none"] == values["empty"] == "", context
    assert values["space"] == "", context


@pytest.mark.integration
@pytest.mark.excel
def test_integer_zero_vs_string_zero(excel_state: CleanupFixtures) -> None:
    """Ensure digit folding preserves numeric meaning for zero values.

    Example:
        >>> sanitize_text("0")
        '0'
    """

    cases = {"int": sanitize_text(0), "str": sanitize_text("0"), "fa": sanitize_text("۰")}
    context = excel_state.context(cases=cases)
    assert len({value for value in cases.values()}) == 1, context


@pytest.mark.integration
@pytest.mark.excel
def test_persian_zero_۰_normalization(excel_state: CleanupFixtures) -> None:
    """Persian digits must fold into ASCII before Excel export.

    Example:
        >>> sanitize_text("۰۹")
        '09'
    """

    normalized = sanitize_text("۰")
    context = excel_state.context(normalized=normalized)
    assert normalized == "0", context


@pytest.mark.integration
@pytest.mark.excel
def test_empty_vs_whitespace_only(excel_state: CleanupFixtures) -> None:
    """Whitespace-only strings collapse into empty outputs for Excel safety."""

    normalized = sanitize_text("   \t")
    context = excel_state.context(normalized=normalized)
    assert normalized == "", context


@pytest.mark.integration
@pytest.mark.excel
def test_zero_width_characters_removal(excel_state: CleanupFixtures) -> None:
    """Zero-width joiners must be stripped to avoid hidden formula payloads."""

    raw = "ک‌لاس"
    normalized = sanitize_text(raw)
    context = excel_state.context(raw=raw, normalized=normalized)
    assert normalized == "کلاس", context


@pytest.mark.integration
@pytest.mark.excel
def test_text_exceeding_excel_cell_limit(excel_state: CleanupFixtures) -> None:
    """Extremely long text remains normalized without crashing streaming writers."""

    long_text = "یادداشت" * 6000  # > 32k characters
    normalized = sanitize_text(long_text)
    context = excel_state.context(length=len(normalized))
    assert len(normalized) == len(long_text), context


@pytest.mark.integration
@pytest.mark.excel
def test_text_with_newlines_and_tabs(excel_state: CleanupFixtures) -> None:
    """Newlines and tabs collapse into single spaces for CSV safety."""

    raw = "شماره\nکلاس\tجدید"
    normalized = sanitize_text(raw)
    context = excel_state.context(raw=raw, normalized=normalized)
    assert "\n" not in normalized and "\t" not in normalized, context


@pytest.mark.integration
@pytest.mark.excel
def test_persian_arabic_latin_digit_mix(excel_state: CleanupFixtures) -> None:
    """Mixed digit scripts fold into a single ASCII-only phone number."""

    raw = "۰۹1٢۳٤۵۶۷۸۹"
    normalized = sanitize_phone(raw)
    context = excel_state.context(raw=raw, normalized=normalized)
    assert normalized == "09123456789", context


@pytest.mark.integration
@pytest.mark.excel
def test_half_width_vs_full_width_numbers(excel_state: CleanupFixtures) -> None:
    """Half-width and full-width numerals normalize identically for Excel."""

    half_width = sanitize_text("123۴۵")
    full_width = sanitize_text("１２３۴۵")
    context = excel_state.context(half_width=half_width, full_width=full_width)
    assert half_width == full_width == "12345", context


@pytest.mark.integration
@pytest.mark.excel
def test_excel_file_over_100mb(excel_state: CleanupFixtures) -> None:
    """Streaming digest protects memory usage while handling 100MB inputs."""

    chunk = ("داده" * 256).encode("utf-8")  # ~1KB chunk
    repeats = 102400  # ~100MB total when streamed

    def generator() -> Iterator[bytes]:
        for _ in range(repeats):
            yield chunk

    digest = secure_digest(generator())
    context = excel_state.context(digest=digest, repeats=repeats)
    assert len(digest) == 64, context


@pytest.mark.integration
@pytest.mark.excel
def test_sheet_with_over_1million_rows(excel_state: CleanupFixtures) -> None:
    """Chunk iterator scales to 1M+ rows without exhausting memory."""

    rows = range(1_000_001)
    chunk_sizes = [len(chunk) for chunk in iter_chunks(rows, 50_000)]
    context = excel_state.context(chunk_sizes=chunk_sizes, total=sum(chunk_sizes))
    assert sum(chunk_sizes) == 1_000_001, context
    assert chunk_sizes[0] == 50_000, context
