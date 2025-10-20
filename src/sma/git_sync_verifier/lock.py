"""File lock utilities for cross-platform repo coordination."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def repo_lock(repo_root: Path) -> Iterator[None]:
    """Acquire exclusive lock within repo root."""
    git_dir = repo_root / ".git"
    lock_path = git_dir / "sync.lock"
    git_dir.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        _acquire(handle)
        yield
    finally:
        _release(handle)
        handle.close()
        try:
            lock_path.unlink(missing_ok=True)
        except AttributeError:  # Python < 3.8 fallback
            if lock_path.exists():
                lock_path.unlink()


def _acquire(handle: "os.FileIO") -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)


def _release(handle: "os.FileIO") -> None:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)
