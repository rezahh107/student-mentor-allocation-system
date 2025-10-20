# --- file: tests/test_logging_payloads.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}

from __future__ import annotations

import hashlib
import json
import logging

import pytest

from sma.core.logging_utils import log_norm_error
from sma.core.normalize import normalize_national_id, normalize_reg_center


@pytest.fixture(autouse=True)
def _reset_caplog(caplog: pytest.LogCaptureFixture) -> None:
    """Ensure each test starts with a clean capture buffer."""

    caplog.clear()


def _single_payload(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    """Extract the single structured payload emitted during a test."""

    assert len(caplog.records) == 1
    record = caplog.records[0]
    payload = json.loads(record.message)
    assert set(payload) == {"code", "sample", "mobile_mask", "nid_hash"}
    return payload


def test_log_norm_error_masks_mobile(caplog: pytest.LogCaptureFixture) -> None:
    """Direct helper usage should mask mobiles as ``09*******12`` shape."""

    with caplog.at_level(logging.WARNING):
        log_norm_error("mobile", "+98 912 345 6712", "نمونه", "mobile.test")
    payload = _single_payload(caplog)
    assert payload["code"] == "mobile.test"
    assert payload["sample"] == "09*******12"
    assert payload["mobile_mask"] == "09*******12"
    assert payload["nid_hash"] is None


def test_log_norm_error_from_normalizer(caplog: pytest.LogCaptureFixture) -> None:
    """Normalization failures must surface structured payloads with samples."""

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_reg_center(True)
    payload = _single_payload(caplog)
    assert payload["code"] == "reg_center.bool"
    assert payload["sample"] == "True"
    assert payload["mobile_mask"] is None
    assert payload["nid_hash"] is None


def test_log_norm_error_hashes_national_id(caplog: pytest.LogCaptureFixture) -> None:
    """National ID failures must hash samples instead of exposing PII."""

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_national_id("0045595418")
    payload = _single_payload(caplog)
    assert payload["code"] == "national_id.checksum"
    assert isinstance(payload["sample"], str)
    assert set(payload["sample"]) == {"*"}
    assert isinstance(payload["nid_hash"], str)
    assert len(payload["nid_hash"]) == 12
    assert "0045595418" not in caplog.text
    assert payload["mobile_mask"] is None


def test_nid_hash_respects_salt(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the salt should affect the emitted hash."""

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("TEST_HASH_SALT", raising=False)
    monkeypatch.setenv("PII_HASH_SALT", "custom_salt")
    with caplog.at_level(logging.WARNING):
        log_norm_error("national_id", "0045595419", "نمونه", "national_id.test")
    payload = _single_payload(caplog)
    expected = hashlib.sha256("custom_salt::0045595419".encode("utf-8")).hexdigest()[:12]
    assert payload["nid_hash"] == expected
    assert payload["sample"] == "**********"


def test_test_hash_salt_override(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """When APP_ENV is dev/test the TEST_HASH_SALT override must apply."""

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("PII_HASH_SALT", "base_salt")
    monkeypatch.setenv("TEST_HASH_SALT", "override_salt")
    with caplog.at_level(logging.WARNING):
        log_norm_error("national_id", "1234567890", "نمونه", "national_id.dev")
    payload = _single_payload(caplog)
    expected = hashlib.sha256("override_salt::1234567890".encode("utf-8")).hexdigest()[:12]
    assert payload["nid_hash"] == expected


def test_test_hash_salt_ignored_in_prod(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prod environments must ignore the TEST_HASH_SALT override."""

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("PII_HASH_SALT", "prod_salt")
    monkeypatch.setenv("TEST_HASH_SALT", "test_only")
    with caplog.at_level(logging.WARNING):
        log_norm_error("national_id", "1234567890", "نمونه", "national_id.prod")
    payload = _single_payload(caplog)
    expected = hashlib.sha256("prod_salt::1234567890".encode("utf-8")).hexdigest()[:12]
    assert payload["nid_hash"] == expected


def test_log_payload_avoids_raw_pii(caplog: pytest.LogCaptureFixture) -> None:
    """Structured payloads must not include raw identifiers."""

    raw_mobile = "00989123456789"
    with caplog.at_level(logging.WARNING):
        log_norm_error("mobile", raw_mobile, "", "mobile.pii_check")
    payload = _single_payload(caplog)
    assert raw_mobile not in caplog.text
    assert "9123456789" not in caplog.text
    assert payload["sample"].startswith("09*******")


def test_log_norm_error_handles_arabic_digits(caplog: pytest.LogCaptureFixture) -> None:
    """Arabic-Indic digits must normalize before masking."""

    with caplog.at_level(logging.WARNING):
        log_norm_error("mobile", "٠٠٩٨٩١٢٣٤٥٦٧٨٩", "", "mobile.arabic_digits")
    payload = _single_payload(caplog)
    assert payload["mobile_mask"] == "09*******89"
    assert payload["sample"] == "09*******89"
