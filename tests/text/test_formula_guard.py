from __future__ import annotations

import pytest

from sma.phase6_import_to_sabt.sanitization import guard_formula


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+VALUE", "'+VALUE"),
        ("12345", "12345"),
    ],
)
def test_leading_apostrophe(value: str, expected: str) -> None:
    assert guard_formula(value) == expected
