"""Centralised Persian error translations for export pathways."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

from sma.phase6_import_to_sabt.errors import (
    EXPORT_IO_FA_MESSAGE,
    EXPORT_VALIDATION_FA_MESSAGE,
    RATE_LIMIT_FA_MESSAGE,
)

_DEFAULT_FALLBACK: Final[str] = "فرایند تولید خروجی با خطا روبرو شد؛ دوباره تلاش کنید."


@dataclass(frozen=True)
class ErrorTranslation:
    code: str
    message: str

    def to_dict(self) -> Mapping[str, str]:
        return {"code": self.code, "message": self.message}


_TRANSLATIONS: Final[dict[str, ErrorTranslation]] = {
    "EXPORT_FAILURE": ErrorTranslation(code="EXPORT_FAILURE", message=EXPORT_IO_FA_MESSAGE),
    "EXPORT_IO_ERROR": ErrorTranslation(code="EXPORT_IO_ERROR", message=EXPORT_IO_FA_MESSAGE),
    "EXPORT_VALIDATION_ERROR": ErrorTranslation(
        code="EXPORT_VALIDATION_ERROR",
        message=EXPORT_VALIDATION_FA_MESSAGE,
    ),
    "EXPORT_RATE_LIMIT": ErrorTranslation(code="EXPORT_RATE_LIMIT", message=RATE_LIMIT_FA_MESSAGE),
}


def resolve_export_error(code: str | None) -> ErrorTranslation:
    """Return a deterministic Persian translation for *code*."""

    if not code:
        return ErrorTranslation(code="EXPORT_FAILURE", message=EXPORT_IO_FA_MESSAGE)
    normalised = code.upper()
    translation = _TRANSLATIONS.get(normalised)
    if translation is not None:
        return translation
    return ErrorTranslation(code=normalised, message=_DEFAULT_FALLBACK)


def export_error_payload(code: str | None) -> Mapping[str, str]:
    translation = resolve_export_error(code)
    return translation.to_dict()


__all__ = ["ErrorTranslation", "export_error_payload", "resolve_export_error"]
