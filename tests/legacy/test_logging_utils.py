import json
import logging

import pytest

from src.core import logging_utils


def test_masking_and_normalization_helpers() -> None:
    assert logging_utils._normalize_mobile_digits("00989123456789") == "09123456789"
    assert logging_utils._normalize_mobile_digits("09891234567890") == "091234567890"
    assert logging_utils._mask_mobile("۰۹۱۲۳۴۵۶۷۸۹") == "09*******89"
    assert logging_utils._derive_mobile_mask("phone", "۹۱۲۳۴۵۶۷۸۹") == "09*******89"
    assert logging_utils._derive_mobile_mask("email", "foo@example.com") is None


def test_nid_hash_uses_test_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_HASH_SALT", "custom-salt")
    digest = logging_utils._derive_nid_hash("national_id", "۱۲۳۴۵۶۷۸۹۰")
    assert digest and len(digest) == 12
    other = logging_utils._derive_nid_hash("nid", "1234567890")
    assert other == digest
    assert logging_utils._derive_nid_hash("name", "123") is None


def test_log_norm_error_outputs_persian_json(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("TEST_HASH_SALT", raising=False)
    caplog.set_level(logging.WARNING)
    logging_utils.log_norm_error("mobile", "۰۹۱۲۳۴۵۶۷۸۹", "فرمت نامعتبر", "MOBILE_INVALID")
    assert caplog.records, "باید لاگ هشدار تولید شود"
    payload = json.loads(caplog.records[0].getMessage())
    assert payload["code"] == "MOBILE_INVALID"
    assert payload["sample"].startswith("09*******")
    assert payload["mobile_mask"].startswith("09*******")
    assert payload["nid_hash"] is None

    caplog.clear()
    logging_utils.log_norm_error("national_id", "۱۲۳۴۵۶۷۸۹۰", "کد ملی مخدوش", "NID_INVALID")
    payload = json.loads(caplog.records[0].getMessage())
    assert payload["code"] == "NID_INVALID"
    assert payload["nid_hash"] is not None
