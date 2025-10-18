from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .metrics import inc_fix, inc_retry
from .retry import retry


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        try:
            try:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX)
                yield
            except ModuleNotFoundError:  # pragma: no cover - Windows fallback
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.flush()
            try:
                lock_path.unlink()
            except OSError:
                pass


def _normalize_content(content: str, *, crlf: bool) -> str:
    normalized = content.replace("\r\n", "\n")
    if crlf:
        normalized = normalized.replace("\n", "\r\n")
    return normalized


def write_atomic(target: Path, content: str, *, crlf: bool = False) -> str:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_content(content, crlf=crlf)
    outcome = "written"

    def _write_once() -> None:
        nonlocal outcome
        with _file_lock(target):
            current = None
            if target.exists():
                current = target.read_text(encoding="utf-8")
            if current == normalized:
                outcome = "unchanged"
                return
            temp_path = target.with_name(target.name + ".part")
            with open(temp_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(normalized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
            outcome = "written"

    try:
        retry(
            _write_once,
            attempts=3,
            retry_on=(PermissionError,),
            after_retry=lambda attempt, error, delay: inc_retry("write_atomic"),
        )
    except Exception:
        inc_fix(target.name, "failed")
        raise
    else:
        inc_fix(target.name, outcome)
    return outcome


__all__ = ["write_atomic"]
