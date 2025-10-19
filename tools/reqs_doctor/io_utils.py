from __future__ import annotations

import hashlib
import os
import random
from pathlib import Path
from typing import Callable, Optional

from .clock import DeterministicClock

_DEFAULT_BACKOFF = 0.05


class AtomicWriteError(RuntimeError):
    pass


def _detect_newline(path: Path) -> str:
    if not path.exists():
        return "\n"
    with path.open("rb") as handle:
        chunk = handle.read(1024)
    if b"\r\n" in chunk:
        return "\r\n"
    return "\n"


def atomic_write(
    path: Path,
    data: str,
    *,
    encoding: str = "utf-8",
    newline: Optional[str] = None,
    attempts: int = 3,
    backoff: float = _DEFAULT_BACKOFF,
    jitter_seed: str = "reqs_doctor",
    sleep: Optional[Callable[[float], None]] = None,
    clock: Optional[DeterministicClock] = None,
) -> None:
    """Windows-safe atomic write preserving newline style."""

    newline = newline or _detect_newline(path)
    temp_path = Path(f"{path}.part")
    sleep = sleep or (lambda _seconds: None)
    hasher = hashlib.blake2b(str(path).encode("utf-8") + jitter_seed.encode("utf-8"))
    rand = random.Random(hasher.digest())

    for attempt in range(1, attempts + 1):
        try:
            with temp_path.open("w", encoding=encoding, newline="") as handle:
                payload = data.replace("\n", newline)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except OSError as exc:  # pragma: no cover - specific to Windows in practice
            if attempt == attempts:
                if clock is not None:
                    clock.tick(seconds=backoff)
                raise AtomicWriteError("نوشتن اتمیک شکست خورد؛ لطفاً مجدداً تلاش کنید.") from exc
            delay = backoff * (2 ** (attempt - 1))
            jitter = rand.uniform(0, backoff)
            sleep(delay + jitter)
            if clock is not None:
                clock.tick(seconds=delay + jitter)
    raise AtomicWriteError("نوشتن اتمیک شکست خورد؛ لطفاً مجدداً تلاش کنید.")
