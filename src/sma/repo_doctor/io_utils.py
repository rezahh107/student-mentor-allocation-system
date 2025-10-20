from __future__ import annotations

import os
import pathlib
from typing import Iterable


def ensure_crlf(text: str) -> str:
    """Normalize newlines to CRLF without double conversion."""

    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def atomic_write(path: pathlib.Path, data: str, newline: str = "\r\n") -> None:
    """Windows-safe atomic write following .part -> fsync -> replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".part")
    with open(temp_path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def append_lines(path: pathlib.Path, lines: Iterable[str]) -> None:
    data = "".join(line if line.endswith("\n") else f"{line}\n" for line in lines)
    atomic_write(path, ensure_crlf(data), newline="")
