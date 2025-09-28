from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import numbers

from ..sanitization import fold_digits, guard_formula, sanitize_phone, sanitize_text
from .constants import DEFAULT_CHUNK_SIZE, RISKY_FORMULA_PREFIXES, SENSITIVE_COLUMNS, SHEET_TEMPLATE
from .metrics import ImportExportMetrics
from .utils import atomic_write, cleanup_partials, iter_chunks, sha256_file

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
                    elif column in {"mentor_name", "first_name", "last_name"} and value:
                        cell.value = guard_formula(value)
                    cells.append(cell)
                sheet.append(cells)
                count += 1
            row_counts[sheet.title] = count
        with atomic_write(
            output_path,
            backoff_seed="xlsx",
            on_retry=on_retry,
            metrics=metrics,
            format_label=format_label,
            sleeper=sleeper,
        ) as handle:
            workbook.save(handle)
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
            value = raw.get(column, "")
            if column in {"group_code", "student_type", "reg_center", "reg_status", "gender"} and value != "":
                value = str(int(value))
            if column == "school_code" and value not in (None, ""):
                try:
                    value = f"{int(value):06d}"
                except (TypeError, ValueError):
                    value = sanitize_text(str(value))
            elif value is None:
                value = ""
            if column in SENSITIVE_COLUMNS:
                value = fold_digits(sanitize_text(str(value)))
                if column == "mobile":
                    value = sanitize_phone(value)
            else:
                value = sanitize_text(str(value))
            if value and value[0] in RISKY_FORMULA_PREFIXES:
                value = guard_formula(value)
            prepared[column] = value
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
