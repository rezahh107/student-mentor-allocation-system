"""Utilities for emitting Excel-safe CSV streams."""
from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Sequence, TextIO, Tuple

__all__ = [
    "BOM_UTF8",
    "ExcelSafeWriter",
    "dangerous_prefixes",
    "make_excel_safe_writer",
    "sanitize_cell",
    "sanitize_row",
]

BOM_UTF8 = "\ufeff"
"""UTF-8 byte order mark emitted when Excel-safe output requires BOM."""

dangerous_prefixes: Tuple[str, ...] = ("=", "+", "-", "@")
"""Prefixes that trigger formula evaluation in spreadsheet software."""

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ZERO_WIDTH_TRANSLATION = {ord(ch): None for ch in ("\u200b", "\u200c", "\u200d", "\ufeff")}


def _normalize_text(value: str) -> str:
    """Normalize text for deterministic exports.

    The transformation applies NFKC normalization, converts Persian/Arabic digits to
    ASCII, and strips zero-width joiners that Excel renders poorly.
    """

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_PERSIAN_DIGITS)
    return normalized.translate(_ZERO_WIDTH_TRANSLATION)


def sanitize_cell(value: object, *, guard_formulas: bool = True) -> str:
    """Convert a cell value into an Excel-safe string.

    Parameters
    ----------
    value:
        Arbitrary cell value that will be converted into text.
    guard_formulas:
        When ``True`` values starting with ``=, +, -, @`` are prefixed with a leading
        apostrophe to prevent evaluation by spreadsheet software.
    """

    text = "" if value is None else str(value)
    text = _normalize_text(text)
    if guard_formulas and text.startswith(dangerous_prefixes) and not text.startswith("'"):
        return f"'{text}"
    return text


def sanitize_row(row: Sequence[object], *, guard_formulas: bool = True) -> List[str]:
    """Sanitize an entire CSV row, preserving streaming semantics."""

    return [sanitize_cell(cell, guard_formulas=guard_formulas) for cell in row]


@dataclass(slots=True)
class ExcelSafeWriter:
    """Thin wrapper over :mod:`csv` that sanitizes values on the fly."""

    handle: TextIO
    guard_formulas: bool = True
    quote_all: bool = False
    line_terminator: str = "\n"
    _writer: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        quoting = csv.QUOTE_ALL if self.quote_all else csv.QUOTE_MINIMAL
        self._writer = csv.writer(self.handle, quoting=quoting, lineterminator=self.line_terminator)

    def writerow(self, row: Sequence[object]) -> None:
        """Write a sanitized row immediately to the underlying handle."""

        self._writer.writerow(sanitize_row(row, guard_formulas=self.guard_formulas))

    def writerows(self, rows: Iterable[Sequence[object]]) -> None:
        """Stream rows to the CSV writer without buffering the iterable."""

        for row in rows:
            self.writerow(row)


def make_excel_safe_writer(
    handle: TextIO,
    *,
    bom: bool = False,
    guard_formulas: bool = True,
    quote_all: bool = False,
    crlf: bool = False,
) -> ExcelSafeWriter:
    """Instantiate an :class:`ExcelSafeWriter` configured for spreadsheet safety."""

    if bom:
        handle.write(BOM_UTF8)
    terminator = "\r\n" if crlf else "\n"
    return ExcelSafeWriter(handle, guard_formulas=guard_formulas, quote_all=quote_all, line_terminator=terminator)
