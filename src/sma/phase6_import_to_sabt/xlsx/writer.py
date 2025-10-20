from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import numbers

from sma.phase6_import_to_sabt.sanitization import sanitize_phone
from sma.phase6_import_to_sabt.app.io_utils import write_atomic
from sma.phase6_import_to_sabt.xlsx.constants import DEFAULT_CHUNK_SIZE, SENSITIVE_COLUMNS, SHEET_TEMPLATE
from sma.phase6_import_to_sabt.xlsx.metrics import ImportExportMetrics
from sma.phase6_import_to_sabt.xlsx.sanitize import (
    normalize_digits_ascii,
    normalize_digits_fa,
    normalize_text,
    safe_cell,
)
from sma.phase6_import_to_sabt.xlsx.utils import cleanup_partials, iter_chunks, sha256_file

EXPORT_COLUMNS: Sequence[str] = (
    "national_id",
    "counter",
    "first_name",
    "last_name",
    "gender",
    "mobile",
    "reg_center",
    "reg_status",
    "group_code",
    "student_type",
    "school_code",
    "mentor_id",
    "mentor_name",
    "mentor_mobile",
    "allocation_date",
    "year_code",
)


@dataclass(slots=True)
class ExportArtifact:
    path: Path
    sha256: str
    byte_size: int
    row_counts: dict[str, int]
    format: str
    excel_safety: dict[str, Any]


class XLSXStreamWriter:
    def __init__(self, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._chunk_size = chunk_size

    def write(
        self,
        rows: Iterable[dict[str, Any]],
        output_path: Path,
        *,
        on_retry: Callable[[int], None] | None = None,
        metrics: ImportExportMetrics | None = None,
        format_label: str = "xlsx",
        sleeper: Callable[[float], None] | None = None,
    ) -> ExportArtifact:
        cleanup_partials(output_path.parent)
        workbook = Workbook(write_only=True)
        default_sheet = workbook.active
        if default_sheet is not None:
            workbook.remove(default_sheet)
        row_counts: dict[str, int] = {}
        sorted_rows = sorted(rows, key=self._sort_key)
        excel_safety = {
            "normalized": True,
            "digit_folded": True,
            "formula_guard": True,
            "sensitive_text": list(SENSITIVE_COLUMNS),
        }
        for index, chunk in enumerate(iter_chunks(sorted_rows, self._chunk_size), start=1):
            sheet = workbook.create_sheet(title=SHEET_TEMPLATE.format(index))
            sheet.append(list(EXPORT_COLUMNS))
            count = 0
            for raw in chunk:
                prepared = self.prepare_row(raw)
                cells: list[WriteOnlyCell] = []
                for column in EXPORT_COLUMNS:
                    value = prepared.get(column, "")
                    cell = WriteOnlyCell(sheet, value=value)
                    if column in SENSITIVE_COLUMNS:
                        cell.number_format = numbers.FORMAT_TEXT
                        cell.data_type = "s"
                    elif isinstance(value, str):
                        cell.data_type = "s"
                    cells.append(cell)
                sheet.append(cells)
                count += 1
            row_counts[sheet.title] = count
        buffer = BytesIO()
        workbook.save(buffer)
        write_atomic(output_path, buffer.getvalue())
        sha256 = sha256_file(output_path)
        byte_size = output_path.stat().st_size
        return ExportArtifact(
            path=output_path,
            sha256=sha256,
            byte_size=byte_size,
            row_counts=row_counts,
            format="xlsx",
            excel_safety=excel_safety,
        )

    def prepare_row(self, raw: dict[str, Any]) -> dict[str, str]:
        prepared: dict[str, str] = {}
        for column in EXPORT_COLUMNS:
            raw_value = raw.get(column, "")
            if raw_value is None:
                raw_text = ""
            else:
                raw_text = str(raw_value)
            normalized = normalize_text(raw_text)
            if column == "school_code" and normalized:
                try:
                    normalized = f"{int(normalized):06d}"
                except (TypeError, ValueError):
                    normalized = normalize_digits_ascii(normalized)
            if column in SENSITIVE_COLUMNS:
                ascii_value = normalize_digits_ascii(normalized)
                if column == "mobile":
                    ascii_value = sanitize_phone(ascii_value)
                prepared[column] = ascii_value
            else:
                visible = normalize_digits_fa(normalized)
                guarded = safe_cell(visible)
                prepared[column] = guarded
        return prepared

    def _sort_key(self, row: dict[str, Any]) -> tuple[str, str, str, str, str]:
        prepared = self.prepare_row(row)

        def _school_key(value: str | None) -> str:
            if value in (None, ""):
                return "999999"
            try:
                return f"{int(value):06d}"
            except (TypeError, ValueError):
                return "999999"

        return (
            prepared.get("year_code", ""),
            prepared.get("reg_center", ""),
            prepared.get("group_code", ""),
            _school_key(prepared.get("school_code")),
            prepared.get("national_id", ""),
        )
