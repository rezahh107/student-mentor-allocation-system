"""Atomic IO helpers honouring Excel safety guarantees."""

from __future__ import annotations

import csv
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence
import unicodedata

_CRITICAL_FORMULA_PREFIXES = ("=", "+", "-", "@")
_SENSITIVE_DEFAULT = {
    "national_id",
    "counter",
    "mobile",
    "mentor_id",
    "school_code",
}


@contextmanager
def _atomic_path(target: Path) -> Iterator[Path]:
    tmp_path = target.with_name(f"{target.name}.part")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        yield tmp_path
        _fsync(tmp_path)
        os.replace(tmp_path, target)
        _fsync(target.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _fsync(path: Path) -> None:
    flags = os.O_RDONLY
    if path.is_dir():
        flags |= getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: Path | str, content: str, *, newline: str = "\n") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _atomic_path(target) as tmp:
        tmp.write_text(content, encoding="utf-8", newline=newline)


def atomic_write_json(path: Path | str, payload: Mapping[str, object]) -> None:
    serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    atomic_write_text(Path(path), f"{serialised}\n")


def _normalize_excel_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    translate_map = {ord("ي"): "ی", ord("ك"): "ک"}
    text = text.translate(translate_map)
    digits_map = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
    text = text.translate(digits_map)
    text = text.replace("\u200c", "").replace("\u200f", "")
    if text and text[0] in _CRITICAL_FORMULA_PREFIXES:
        text = f"'{text}"
    return text


def _quote_sensitive(header: str, value: str, *, sensitive: set[str]) -> str:
    if header in sensitive and not value.startswith("'"):
        return f"'{value}"
    return value


def atomic_write_excel_safe_csv(
    path: Path | str,
    headers: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    sensitive_columns: Iterable[str] | None = None,
) -> None:
    target = Path(path)
    sensitive = set(sensitive_columns or _SENSITIVE_DEFAULT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _atomic_path(target) as tmp:
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(headers)
            for row in rows:
                normalized: list[str] = []
                for header in headers:
                    value = _normalize_excel_value(row.get(header, ""))
                    value = _quote_sensitive(header, value, sensitive=sensitive)
                    normalized.append(value)
                writer.writerow(normalized)


__all__ = [
    "atomic_write_excel_safe_csv",
    "atomic_write_json",
    "atomic_write_text",
]
