"""Tests for require_idempotency_key dependency helper."""

import pytest
from fastapi import HTTPException

from sma.phase6_import_to_sabt.deps import require_idempotency_key


def test_missing_header_raises_required() -> None:
    with pytest.raises(HTTPException) as ex:
        require_idempotency_key(None)
    err = ex.value
    assert err.status_code == 400
    assert isinstance(err.detail, dict)
    assert err.detail.get("code") == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "\u200b", "\u200c", "\u200d", "\ufeff", "\u200b  \u200c"],
)
def test_empty_or_zw_chars_rejected(raw: str) -> None:
    with pytest.raises(HTTPException) as ex:
        require_idempotency_key(raw)
    assert ex.value.detail.get("code") == "IDEMPOTENCY_KEY_REQUIRED"


def test_too_long_rejected() -> None:
    too_long = "x" * 129
    with pytest.raises(HTTPException) as ex:
        require_idempotency_key(too_long)
    assert ex.value.status_code == 400
    assert ex.value.detail.get("code") == "INVALID_IDEMPOTENCY_KEY"


def test_valid_key_passes() -> None:
    key = "8f3e6b5a-6b3a-4d3e-9f0a-1b2c3d4e5f60"
    assert require_idempotency_key(key) == key
