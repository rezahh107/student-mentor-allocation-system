"""Filesystem helpers honouring atomic writes and Excel safety rules."""

from __future__ import annotations

import io
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Callable

NORMALIZE_TABLE = str.maketrans({"ي": "ی", "ك": "ک"})
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
FORMULA_PREFIXES = ("=", "+", "-", "@")


def normalize_text(value: str) -> str:
    """Normalize text using NFKC, digit folding, and y/ک unification."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)
    normalized = normalized.translate(NORMALIZE_TABLE)
    return "".join(ch for ch in normalized if ch.isprintable() or ch == "\n").strip()


def formula_guard(value: str) -> str:
    """Prefix dangerous Excel formulas with `'` to neutralize them."""

    if not value:
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def ensure_crlf(data: str) -> str:
    """Ensure Windows-style CRLF newlines."""

    return data.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    attempts: int = 3,
    jitter: Callable[[], float] | None = None,
) -> None:
    """Write bytes atomically using `.part` temp files and fsync."""

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        fd, temp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{path.name}.", suffix=".part")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except Exception as exc:  # pragma: no cover - unexpected IO failure
            last_error = exc
            try:
                temp_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:  # pragma: no cover - py3.10 compatibility
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
            if attempt == attempts:
                raise
            if jitter is not None:
                jitter()
        finally:
            try:
                temp_path.unlink(missing_ok=True)  # type: ignore[call-arg]
            except TypeError:  # pragma: no cover
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
    if last_error is not None:  # pragma: no cover - defensive guard
        raise last_error


def atomic_write_text(path: Path, data: str, *, attempts: int = 3, jitter: Callable[[], float] | None = None) -> None:
    """Atomic text writer that delegates to :func:`atomic_write_bytes`."""

    atomic_write_bytes(path, data.encode("utf-8"), attempts=attempts, jitter=jitter)


def build_csv_rows(rows: list[list[str]]) -> bytes:
    """Serialize rows as UTF-8 CSV with BOM, CRLF, and quoted sensitive values."""

    buffer = io.StringIO()
    for row in rows:
        safe = [formula_guard(normalize_text(cell)) for cell in row]
        quoted = ['"' + cell.replace('"', '""') + '"' for cell in safe]
        buffer.write(",".join(quoted))
        buffer.write("\r\n")
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


__all__ = [
    "atomic_write_bytes",
    "atomic_write_text",
    "build_csv_rows",
    "ensure_crlf",
    "formula_guard",
    "normalize_text",
]

