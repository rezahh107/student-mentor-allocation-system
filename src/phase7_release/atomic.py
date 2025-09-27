"""Atomic file operations with deterministic semantics."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable


class AtomicWriteError(RuntimeError):
    """Raised when atomic file writing fails."""


def atomic_write(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=path.name, suffix=".part", dir=path.parent)
        tmp_fd = fd
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception as exc:  # noqa: BLE001
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise AtomicWriteError(str(exc)) from exc


def atomic_write_lines(path: Path, lines: Iterable[str]) -> None:
    data = "\n".join(lines)
    if not data.endswith("\n"):
        data += "\n"
    atomic_write(path, data.encode("utf-8"))


__all__ = ["atomic_write", "atomic_write_lines", "AtomicWriteError"]
