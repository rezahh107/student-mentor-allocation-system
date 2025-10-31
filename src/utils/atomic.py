"""Project-wide atomic file helpers bridging legacy and v6 exporters."""

from __future__ import annotations

from pathlib import Path
from typing import ContextManager

from sma.utils.atomic_io import atomic_output_path

__all__ = ["atomic_output_path", "temporary_atomic_path"]


def temporary_atomic_path(path: Path | str) -> ContextManager[Path]:
    """Backwards-compatible wrapper around :func:`atomic_output_path`.

    Exporters that need a physical path (e.g. OpenPyXL) can request a
    temporary filename, write their payload, and rely on the context manager
    to ``fsync`` and atomically promote it when the block exits.
    """

    return atomic_output_path(path)
