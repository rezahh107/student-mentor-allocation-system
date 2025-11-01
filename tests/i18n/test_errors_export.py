from __future__ import annotations

from src.i18n.errors import export_error_payload
from src.sma.phase6_import_to_sabt.models import ExportErrorCode
from sma.phase6_import_to_sabt.errors import (
    EXPORT_EMPTY_FA_MESSAGE,
    EXPORT_IO_FA_MESSAGE,
    EXPORT_PROFILE_UNKNOWN_FA_MESSAGE,
    EXPORT_VALIDATION_FA_MESSAGE,
    RATE_LIMIT_FA_MESSAGE,
)

EXPECTED_MESSAGES = {
    ExportErrorCode.EXPORT_IO_ERROR.value: EXPORT_IO_FA_MESSAGE,
    ExportErrorCode.EXPORT_VALIDATION_ERROR.value: EXPORT_VALIDATION_FA_MESSAGE,
    ExportErrorCode.EXPORT_EMPTY.value: EXPORT_EMPTY_FA_MESSAGE,
    ExportErrorCode.EXPORT_PROFILE_UNKNOWN.value: EXPORT_PROFILE_UNKNOWN_FA_MESSAGE,
    "EXPORT_RATE_LIMIT": RATE_LIMIT_FA_MESSAGE,
    "EXPORT_FAILURE": EXPORT_IO_FA_MESSAGE,
}


def test_export_error_translations_cover_all_codes() -> None:
    for code, message in EXPECTED_MESSAGES.items():
        payload = export_error_payload(code)
        assert payload["code"] == code
        assert payload["message"] == message

    guarded = export_error_payload("export_empty")
    assert guarded["code"] == "EXPORT_EMPTY"
    assert guarded["message"] == EXPECTED_MESSAGES["EXPORT_EMPTY"]

    unknown = export_error_payload("UNSEEN_ERROR")
    assert unknown["code"] == "UNSEEN_ERROR"
    assert "خطا" in unknown["message"]

    fallback = export_error_payload(None)
    assert fallback["code"] == "EXPORT_FAILURE"
    assert fallback["message"] == EXPECTED_MESSAGES["EXPORT_FAILURE"]
