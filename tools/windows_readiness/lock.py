"""Cooperative file locking for readiness runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class ReadinessLock:
    """Platform-aware advisory file lock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Optional[int] = None
        self._file = None

    def acquire(self) -> None:
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "w")
        handle = self._file.fileno()
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self._file.close()
            self._file = None
            raise
        self._handle = handle

    def release(self) -> None:
        if self._file is None:
            return
        handle = self._handle
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
            self._handle = None

    def __enter__(self) -> "ReadinessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


__all__ = ["ReadinessLock"]

