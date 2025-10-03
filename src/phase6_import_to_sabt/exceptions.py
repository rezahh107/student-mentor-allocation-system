from __future__ import annotations

"""Shared exporter exceptions for ImportToSabt pipeline."""


class ExportValidationError(ValueError):
    """Raised when validation of export inputs or rows fails."""


class ExportIOError(RuntimeError):
    """Raised when IO operations fail during export finalization."""

    def __init__(self, message: str = "EXPORT_IO_ERROR") -> None:
        super().__init__(message)


__all__ = ["ExportValidationError", "ExportIOError"]
