"""Streaming Excel-safe CSV exporter with Persian data hygiene."""
from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence, TextIO

from src.phase3_allocation.policy import PERSIAN_DIGITS, ZERO_WIDTH_CHARS

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_ZERO_WIDTH_EXTRA = {"\u200d"}


def normalize_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    for char in ZERO_WIDTH_CHARS.union(_ZERO_WIDTH_EXTRA):
        text = text.replace(char, "")
    text = text.replace("ك", "ک").replace("ي", "ی")
    if any(char in PERSIAN_DIGITS for char in text):
        text = "".join(PERSIAN_DIGITS.get(char, char) for char in text)
    return text


def _apply_excel_guard(text: str) -> str:
    if not text:
        return text
    if text.startswith(_FORMULA_PREFIXES) or text.startswith("\t"):
        return "'" + text
    return text


@dataclass(frozen=True)
class ExcelSafeExporter:
    """Write CSV rows while enforcing Excel safety measures."""

    headers: Sequence[str]

    def export(
        self,
        rows: Iterable[Mapping[str, object]],
        handle: TextIO,
        *,
        include_bom: bool,
        excel_safe: bool,
    ) -> None:
        if include_bom:
            handle.write("\ufeff")
        writer = csv.DictWriter(
            handle,
            fieldnames=list(self.headers),
            quoting=csv.QUOTE_ALL,
            extrasaction="ignore",
        )
        writer.writeheader()
        for sanitized in iter_rows(
            rows,
            headers=self.headers,
            excel_safe=excel_safe,
        ):
            writer.writerow(sanitized)


def iter_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    headers: Sequence[str],
    excel_safe: bool,
) -> Iterator[dict[str, str]]:
    """Yield sanitized rows ready for Excel-safe CSV output.

    This helper performs normalization and Excel formula guarding lazily so that
    callers can stream rows directly to disk without materialising the entire
    dataset in memory.
    """

    for row in rows:
        sanitized: dict[str, str] = {}
        for header in headers:
            cell = normalize_cell(row.get(header, ""))
            if excel_safe:
                cell = _apply_excel_guard(cell)
            sanitized[header] = cell
        yield sanitized


def export_to_path(
    rows: Iterable[Mapping[str, object]],
    *,
    headers: Sequence[str],
    path: str | Path,
    include_bom: bool,
    excel_safe: bool,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        exporter = ExcelSafeExporter(headers=headers)
        exporter.export(rows, handle, include_bom=include_bom, excel_safe=excel_safe)


__all__ = [
    "ExcelSafeExporter",
    "export_to_path",
    "normalize_cell",
    "iter_rows",
]

