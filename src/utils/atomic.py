"""Project-wide atomic file helpers bridging legacy and v6 exporters."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Callable, ContextManager, cast
import os
import tempfile

from sma.utils.atomic_io import atomic_output_path  # type: ignore[import-not-found]

__all__ = ["atomic_output_path", "temporary_atomic_path", "write_atomic"]


def temporary_atomic_path(path: Path | str) -> ContextManager[Path]:
    """Backwards-compatible wrapper around :func:`atomic_output_path`.

    Exporters that need a physical path (e.g. OpenPyXL) can request a
    temporary filename, write their payload, and rely on the context manager
    to ``fsync`` and atomically promote it when the block exits.
    """

    return cast(ContextManager[Path], atomic_output_path(path))


def write_atomic(path: str | Path, writer: Callable[[BinaryIO], None]) -> None:
    """Persist *path* atomically by streaming into a ``.part`` file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".part", dir=target.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
