from __future__ import annotations

import csv
import itertools
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import xlsxwriter

from phase6_import_to_sabt.sanitization import guard_formula, sanitize_phone, sanitize_text


EXPORT_COLUMNS: tuple[str, ...] = (
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

NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {
        "national_id",
        "counter",
        "gender",
        "mobile",
        "reg_center",
        "reg_status",
        "group_code",
        "student_type",
        "school_code",
        "mentor_id",
        "mentor_mobile",
        "year_code",
    }
)

PHONE_COLUMNS: frozenset[str] = frozenset({"mobile", "mentor_mobile"})
TEXT_COLUMNS: frozenset[str] = frozenset(
    {
        "national_id",
        "counter",
        "first_name",
        "last_name",
        "mentor_id",
        "mentor_name",
        "year_code",
    }
)


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    name: str
    sha256: str
    byte_size: int
    row_count: int
    sheets: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ExportResult:
    files: list[ExportedFile]
    total_rows: int
    excel_safety: dict[str, Any]


class ExportWriter:
    def __init__(
        self,
        *,
        columns: Sequence[str] = EXPORT_COLUMNS,
        sensitive_columns: Sequence[str] = (),
        newline: str = "\r\n",
        include_bom: bool = False,
        chunk_size: int = 50_000,
        formula_guard: bool = True,
        sheet_template: str = "Sheet_{index:03d}",
        sha256_factory: Callable[[Path], str] | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._columns = tuple(columns)
        self._sensitive = tuple(sensitive_columns)
        self._newline = newline
        self._include_bom = include_bom
        self._chunk_size = chunk_size
        self._formula_guard = formula_guard
        self._sheet_template = sheet_template
        self._sha256 = sha256_factory or _sha256_file

    def write_csv(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        path_factory: Callable[[int], Path],
    ) -> ExportResult:
        files: list[ExportedFile] = []
        total_rows = 0
        for index, chunk in enumerate(_prepared_chunks(rows, self._chunk_size, self._prepare_row), start=1):
            path = path_factory(index)
            byte_size = self._write_csv_chunk(path, chunk)
            digest = self._sha256(path)
            files.append(
                ExportedFile(
                    path=path,
                    name=path.name,
                    sha256=digest,
                    byte_size=byte_size,
                    row_count=len(chunk),
                )
            )
            total_rows += len(chunk)
        safety = {
            "normalized": True,
            "digit_folded": True,
            "formula_guard": self._formula_guard,
            "always_quote_columns": list(self._sensitive),
            "newline": self._newline,
            "bom": self._include_bom,
            "numeric_columns": list(NUMERIC_COLUMNS),
        }
        return ExportResult(files=files, total_rows=total_rows, excel_safety=safety)

    def write_xlsx(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        path_factory: Callable[[int], Path],
    ) -> ExportResult:
        workbook_options = {
            "constant_memory": True,
            "strings_to_numbers": False,
            "strings_to_formulas": False,
        }
        row_counts: dict[str, int] = {}
        total_rows = 0
        path = path_factory(1)
        temp_path = path.with_suffix(path.suffix + ".part")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with xlsxwriter.Workbook(temp_path.as_posix(), workbook_options) as workbook:
                header_format = workbook.add_format({"bold": True})
                text_format = workbook.add_format({"num_format": "@"})
                column_formats = [text_format if column in self._sensitive else None for column in self._columns]
                for index, chunk in enumerate(
                    _prepared_chunks(rows, self._chunk_size, self._prepare_row),
                    start=1,
                ):
                    sheet_name = self._sheet_template.format(index=index)
                    worksheet = workbook.add_worksheet(sheet_name)
                    worksheet.write_row(0, 0, list(self._columns), header_format)
                    for col_idx, fmt in enumerate(column_formats):
                        if fmt is not None:
                            worksheet.set_column(col_idx, col_idx, None, fmt)
                    row_index = 1
                    count = 0
                    for prepared in chunk:
                        for col_idx, value in enumerate(prepared):
                            worksheet.write_string(row_index, col_idx, value)
                        row_index += 1
                        count += 1
                    row_counts[sheet_name] = count
                    total_rows += count
                if not row_counts:
                    sheet_name = self._sheet_template.format(index=1)
                    worksheet = workbook.add_worksheet(sheet_name)
                    worksheet.write_row(0, 0, list(self._columns), header_format)
                    for col_idx, fmt in enumerate(column_formats):
                        if fmt is not None:
                            worksheet.set_column(col_idx, col_idx, None, fmt)
                    row_counts[sheet_name] = 0
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
        with open(temp_path, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        byte_size = path.stat().st_size
        digest = self._sha256(path)
        sheets = tuple(sorted(row_counts.items()))
        files: list[ExportedFile] = [
            ExportedFile(
                path=path,
                name=path.name,
                sha256=digest,
                byte_size=byte_size,
                row_count=total_rows,
                sheets=sheets,
            )
        ]
        safety = {
            "normalized": True,
            "digit_folded": True,
            "formula_guard": self._formula_guard,
            "sensitive_text_columns": list(self._sensitive),
            "numeric_columns": list(NUMERIC_COLUMNS),
            "backend": "xlsxwriter",
        }
        return ExportResult(files=files, total_rows=total_rows, excel_safety=safety)

    def _write_csv_chunk(self, path: Path, chunk: list[list[str]]) -> int:
        encoding = "utf-8"
        with atomic_writer(path, newline="", encoding=encoding) as handle:
            if self._include_bom:
                handle.write("\ufeff")
            writer = csv.writer(handle, lineterminator=self._newline, quoting=csv.QUOTE_ALL)
            writer.writerow(self._columns)
            for prepared in chunk:
                writer.writerow(prepared)
        return path.stat().st_size

    def _prepare_row(self, raw: dict[str, Any]) -> list[str]:
        prepared: list[str] = []
        for column in self._columns:
            value = raw.get(column)
            if value is None:
                text = ""
            elif isinstance(value, str):
                text = value
            else:
                text = str(value)
            if text and not text.isascii():
                if column in PHONE_COLUMNS:
                    text = sanitize_phone(text)
                elif column in TEXT_COLUMNS:
                    text = sanitize_text(text)
            if self._formula_guard and text:
                first = text[0]
                if first in ("=", "+", "-", "@", "\t", "'", '"'):
                    text = guard_formula(text)
            if column == "school_code" and text:
                try:
                    text = f"{int(text):06d}"
                except ValueError:
                    text = text.zfill(6)
            prepared.append(text)
        return prepared


def _prepared_chunks(
    rows: Iterable[dict[str, Any]],
    size: int,
    prepare: Callable[[dict[str, Any]], list[str]],
) -> Iterable[list[list[str]]]:
    iterator = iter(rows)
    while True:
        batch = list(itertools.islice(iterator, size))
        if not batch:
            break
        yield [prepare(item) for item in batch]


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


@contextmanager
def atomic_writer(path: Path, *, newline: str = "\n", encoding: str = "utf-8"):
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "w", encoding=encoding, newline=newline) as handle:
        try:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            if temp_path.exists():
                temp_path.unlink()
            raise
    os.replace(temp_path, path)


__all__ = [
    "ExportResult",
    "ExportWriter",
    "ExportedFile",
    "EXPORT_COLUMNS",
    "NUMERIC_COLUMNS",
    "PHONE_COLUMNS",
    "TEXT_COLUMNS",
]

