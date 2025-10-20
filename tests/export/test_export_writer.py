from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from sma.phase6_import_to_sabt.export_writer import ExportWriter


@pytest.fixture
def clean_export_state(tmp_path: Path) -> Iterator[Path]:
    # Ensure deterministic cleanup for concurrent test execution.
    for artifact in tmp_path.iterdir():
        if artifact.is_file():
            artifact.unlink()
    yield tmp_path
    for artifact in tmp_path.glob("**/*"):
        if artifact.is_file():
            artifact.unlink()


def _path_factory(tmp_path: Path):
    def _factory(index: int) -> Path:
        return tmp_path / f"export-{uuid4().hex}-{index}.csv"

    return _factory


def test_excel_safety_includes_boolean_flag(clean_export_state: Path) -> None:
    tmp_path = clean_export_state
    writer = ExportWriter(sensitive_columns=("national_id", "mobile"))
    rows = [
        {"national_id": "001", "mobile": "09000000001", "first_name": "A"},
        {"national_id": "002", "mobile": "09000000002", "first_name": "B"},
    ]
    result = writer.write_csv(rows, path_factory=_path_factory(tmp_path))
    safety = result.excel_safety
    assert safety["always_quote"] is True, safety
    assert set(safety["always_quote_columns"]) == {"national_id", "mobile"}, safety


def test_excel_safety_false_when_no_sensitive_columns(clean_export_state: Path) -> None:
    tmp_path = clean_export_state
    writer = ExportWriter(sensitive_columns=())
    rows = [{"national_id": "003"}]
    result = writer.write_csv(rows, path_factory=_path_factory(tmp_path))
    safety = result.excel_safety
    assert safety["always_quote"] is False, safety
    assert safety["always_quote_columns"] == [], safety
