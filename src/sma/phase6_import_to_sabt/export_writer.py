"""Compatibility shim importing the shared Excel writer implementation."""

from sma.export.excel_writer import (  # noqa: F401
    EXPORT_COLUMNS,
    ExportResult,
    ExportWriter,
    ExportedFile,
    NUMERIC_COLUMNS,
    PHONE_COLUMNS,
    TEXT_COLUMNS,
    atomic_writer,
)

__all__ = [
    "ExportResult",
    "ExportWriter",
    "ExportedFile",
    "EXPORT_COLUMNS",
    "NUMERIC_COLUMNS",
    "PHONE_COLUMNS",
    "TEXT_COLUMNS",
    "atomic_writer",
]

