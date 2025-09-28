from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterable, Iterator, TextIO

__all__ = ["atomic_writer", "atomic_write_text"]


def _fsync_directory(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def atomic_writer(target: Path, *, mode: str = "w", encoding: str | None = "utf-8") -> Iterator[TextIO]:
    target = Path(target)
    tmp_dir = target.parent
    tmp_fd: int
    tmp_path: str
    tmp_fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, prefix=target.name, suffix=".part")
    try:
        with os.fdopen(tmp_fd, mode, encoding=encoding) as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        _fsync_directory(target.parent)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def atomic_write_text(target: Path, chunks: Iterable[str], *, encoding: str = "utf-8", newline: str = "\n") -> None:
    with atomic_writer(target, mode="w", encoding=encoding) as handle:
        for chunk in chunks:
            handle.write(chunk)
            if newline and not chunk.endswith(newline):
                handle.write(newline)
