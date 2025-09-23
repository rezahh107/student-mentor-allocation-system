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

from src.core.logging_utils import log_norm_error
from src.core.normalize import normalize_national_id, normalize_reg_center


@pytest.fixture(autouse=True)
def _reset_caplog(caplog: pytest.LogCaptureFixture) -> None:
    """Ensure each test starts with a clean capture buffer."""

    caplog.clear()


def _single_payload(caplog: pytest.LogCaptureFixture) -> dict[str, object]:
    """Extract the single structured payload emitted during a test."""

    assert len(caplog.records) == 1
    record = caplog.records[0]
    payload = json.loads(record.message)
    assert set(payload) == {
        "event",
        "field",
        "reason",
        "code",
        "sample",
        "mobile_mask",
        "nid_hash",
    }
    assert payload["event"] == "normalization_failure"
    return payload


def test_log_norm_error_masks_mobile(caplog: pytest.LogCaptureFixture) -> None:
    """Direct helper usage should mask mobiles as ``09*******12`` shape."""

    with caplog.at_level(logging.WARNING):
        log_norm_error("mobile", "+98 912 345 6712", "نمونه", "mobile.test")
    payload = _single_payload(caplog)
    assert payload["field"] == "mobile"
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
    assert payload["field"] == "reg_center"
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
    assert payload["field"] == "national_id"
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

    monkeypatch.setenv("NID_HASH_SALT", "custom_salt")
    with caplog.at_level(logging.WARNING):
        log_norm_error("national_id", "0045595419", "نمونه", "national_id.test")
    payload = _single_payload(caplog)
    expected = hashlib.sha256("custom_salt::0045595419".encode("utf-8")).hexdigest()[:12]
    assert payload["nid_hash"] == expected
    assert payload["sample"] == "**********"
