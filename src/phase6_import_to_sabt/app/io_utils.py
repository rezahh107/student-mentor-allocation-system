"""IO utilities for deterministic, atomic file operations."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable


def write_atomic(
    path: Path,
    data: bytes,
    *,
    attempts: int = 3,
    base_delay: float = 0.01,
    on_retry: Callable[[int], None] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> None:
    """Write ``data`` to ``path`` atomically within its directory."""

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f".{path.name}.tmp"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        fd, temp_name = tempfile.mkstemp(prefix=prefix, suffix=".part", dir=str(directory))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except Exception as exc:  # pragma: no cover - exceptional path
            last_error = exc
            if on_retry is not None:
                on_retry(attempt)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            if attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            if sleeper is not None:
                sleeper(delay)
            else:
                time.sleep(delay)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    if last_error is not None:  # pragma: no cover - defensive
        raise last_error


__all__ = ["write_atomic"]

