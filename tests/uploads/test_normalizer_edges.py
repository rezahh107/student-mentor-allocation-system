"""Edge-case coverage for roster text normalization helpers."""

from __future__ import annotations

import pytest

from sma.phase2_uploads.normalizer import fold_digits, normalize_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", ""),
        ("  \u200cك", "ک"),
        ("٠١٢٣", "0123"),
        ("۰۱۲۳", "0123"),
        ("null", "null"),
        ("None", "None"),
    ],
)
def test_normalize_text_handles_null_like_tokens(raw: str | None, expected: str | None) -> None:
    result = normalize_text(raw)
    assert result == expected


def test_fold_digits_handles_large_numbers() -> None:
    raw = "۰" * 128
    folded = fold_digits(raw)
    assert folded == "0" * 128
