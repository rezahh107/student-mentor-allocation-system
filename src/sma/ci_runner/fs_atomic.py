"""Atomic filesystem utilities tailored for Tailored v2.4."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Iterable, Union

Pathish = Union[str, os.PathLike[str]]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _fsync_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        # Nothing we can do if fsync is unsupported (e.g. some CI filesystems).
        pass


def _fsync_path(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return
    try:
        _fsync_fd(fd)
    finally:
        os.close(fd)


def fsync_directory(path: Pathish) -> None:
    """Fsync the provided directory if possible."""

    _fsync_path(Path(path))


def _write_atomic(target: Path, data: bytes) -> None:
    _ensure_parent(target)
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        _fsync_fd(handle.fileno())
    os.replace(tmp, target)
    _fsync_path(target)
    _fsync_path(target.parent)


def atomic_write_text(path: Pathish, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically using UTF-8 by default."""

    target = Path(path)
    _write_atomic(target, content.encode(encoding))


def atomic_write_bytes(path: Pathish, content: bytes) -> None:
    """Write raw ``content`` to ``path`` atomically."""

    target = Path(path)
    _write_atomic(target, content)


def atomic_touch(path: Pathish) -> None:
    """Create an empty file atomically if it does not exist."""

    atomic_write_bytes(path, b"")


def rotate_directory(path: Pathish, *, rotated_name_prefix: str = "prev_", fsync: bool = True) -> Path:
    """Rotate an existing directory out of the way and recreate an empty one.

    The rotation uses an atomic rename into ``parent/prev_<name>_<uuid>``.  The
    rotated directory path is returned; callers may decide whether to delete it.
    """

    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        if fsync:
            fsync_directory(parent)
            fsync_directory(target)
        return target

    suffix = uuid.uuid4().hex[:8]
    rotated = parent / f"{rotated_name_prefix}{target.name}_{suffix}"
    if rotated.exists():
        shutil.rmtree(rotated)
    os.replace(target, rotated)
    if fsync:
        fsync_directory(rotated)
        fsync_directory(parent)

    target.mkdir(parents=True, exist_ok=True)
    if fsync:
        fsync_directory(target)
        fsync_directory(parent)
    return rotated


def ensure_directories(paths: Iterable[Pathish]) -> None:
    """Ensure that all directories in ``paths`` exist."""

    for item in paths:
        Path(item).mkdir(parents=True, exist_ok=True)
