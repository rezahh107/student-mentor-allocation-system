from __future__ import annotations

import csv
import io
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

CONTROL_CHARS = dict.fromkeys(range(0, 32))
SENSITIVE_PREFIXES = ("=", "+", "-", "@")


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    normalized = normalized.replace("\u200c", "")
    normalized = normalized.translate(CONTROL_CHARS)
    return normalized


def _prepare_cell(raw: object) -> str:
    text = "" if raw is None else str(raw)
    text = _normalize_text(text)
    if text and text[0] in SENSITIVE_PREFIXES:
        text = "'" + text
    return text


def render_safe_csv(
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    newline: str = "\r\n",
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator=newline)
    writer.writerow([_prepare_cell(col) for col in header])
    for row in rows:
        writer.writerow([_prepare_cell(value) for value in row])
    return buffer.getvalue()


def write_safe_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    from .files import write_atomic  # Local import to avoid cycle.

    content = render_safe_csv(header, rows)
    write_atomic(Path(path), content, crlf=True)
    return content


__all__ = ["render_safe_csv", "write_safe_csv"]
