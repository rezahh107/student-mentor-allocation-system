from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from phase6_import_to_sabt.app.timing import MonotonicTimer, Timer

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from phase6_import_to_sabt.obs.metrics import ServiceMetrics


_FORMULA_PREFIXES = ("=", "+", "-", "@")
_ZERO_WIDTH_TRANSLATION = {ord(ch): None for ch in ["\u200b", "\u200c", "\u200d", "\ufeff"]}
_DIGIT_TRANSLATION = {
    ord("۰"): "0",
    ord("۱"): "1",
    ord("۲"): "2",
    ord("۳"): "3",
    ord("۴"): "4",
    ord("۵"): "5",
    ord("۶"): "6",
    ord("۷"): "7",
    ord("۸"): "8",
    ord("۹"): "9",
    ord("٠"): "0",
    ord("١"): "1",
    ord("٢"): "2",
    ord("٣"): "3",
    ord("٤"): "4",
    ord("٥"): "5",
    ord("٦"): "6",
    ord("٧"): "7",
    ord("٨"): "8",
    ord("٩"): "9",
}
_YA_KE_TRANSLATION = {ord("ي"): "ی", ord("ك"): "ک"}
_ALLOWED_WHITESPACE = {" "}


def normalize_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_YA_KE_TRANSLATION)
    text = text.translate(_DIGIT_TRANSLATION)
    text = text.translate(_ZERO_WIDTH_TRANSLATION)
    text = text.replace("\r", " ").replace("\n", " ")
    text = "".join(ch for ch in text if ch >= " " or ch in _ALLOWED_WHITESPACE)
    return text.strip()


def _guard_formula(text: str, raw: Any | None = None) -> str:
    if not text:
        return text
    raw_value = "" if raw is None else str(raw)
    candidate = unicodedata.normalize("NFKC", raw_value)
    candidate = candidate.translate(_ZERO_WIDTH_TRANSLATION)
    stripped = candidate.lstrip()
    if not stripped:
        return text
    if stripped[0] in _FORMULA_PREFIXES or stripped.startswith("\t"):
        return "'" + text
    return text


def _ensure_sequence(row: Any, header: Sequence[str]) -> list[str]:
    if isinstance(row, Mapping):
        ordered = []
        for column in header:
            raw = row.get(column, "")
            ordered.append(_guard_formula(normalize_cell(raw), raw=raw))
    else:
        seq = list(row)
        if len(seq) != len(header):
            raise ValueError("Row length does not match header length")
        ordered = [_guard_formula(normalize_cell(cell), raw=cell) for cell in seq]
    return ordered


def _serialize_row(values: Sequence[str], *, quote_mask: Sequence[bool], newline: str) -> str:
    rendered = []
    for value, force_quote in zip(values, quote_mask):
        escaped = value.replace('"', '""')
        needs_quote = force_quote or "," in escaped or "\r" in escaped or "\n" in escaped
        if needs_quote:
            rendered.append(f'"{escaped}"')
        else:
            rendered.append(escaped)
    return ",".join(rendered) + newline


def write_csv_atomic(
    destination: Path,
    rows: Iterable[Any],
    *,
    header: Sequence[str],
    sensitive_fields: Sequence[str] | Sequence[int] = (),
    metrics: "ServiceMetrics" | None = None,
    timer: Timer | None = None,
    include_bom: bool = True,
    newline: str = "\r\n",
    fsync: bool = True,
) -> Path:
    timer = timer or MonotonicTimer()
    timing_handle = timer.start()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    sensitive_set: set[int]
    if sensitive_fields and isinstance(sensitive_fields[0], str):  # type: ignore[index]
        sensitive_set = {header.index(field) for field in sensitive_fields if field in header}  # type: ignore[arg-type]
    else:
        sensitive_set = {int(index) for index in sensitive_fields}  # type: ignore[list-item]
    quote_mask = [idx in sensitive_set for idx in range(len(header))]
    total_bytes = 0
    try:
        with temp_path.open("wb") as handle_file:
            if include_bom:
                bom = "\ufeff".encode("utf-8")
                handle_file.write(bom)
                total_bytes += len(bom)
            header_line = _serialize_row(
                [normalize_cell(item) for item in header],
                quote_mask=[True] * len(header),
                newline=newline,
            )
            header_bytes = header_line.encode("utf-8")
            handle_file.write(header_bytes)
            total_bytes += len(header_bytes)
            for row in rows:
                ordered = _ensure_sequence(row, header)
                serialized = _serialize_row(ordered, quote_mask=quote_mask, newline=newline)
                encoded = serialized.encode("utf-8")
                handle_file.write(encoded)
                total_bytes += len(encoded)
            handle_file.flush()
            if fsync:
                os.fsync(handle_file.fileno())
        os.replace(temp_path, destination)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    duration = timing_handle.elapsed()
    if metrics:
        metrics.exporter_duration_seconds.observe(duration)
        metrics.exporter_bytes_total.inc(total_bytes)
    return destination


__all__ = ["normalize_cell", "write_csv_atomic"]
