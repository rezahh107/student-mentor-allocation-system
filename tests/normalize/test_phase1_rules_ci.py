from __future__ import annotations

import pytest

from src.core.normalize import normalize_gender, normalize_reg_center, normalize_reg_status
from src.phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text


def test_text_and_phone_rules() -> None:
    text = sanitize_text("\u200cحكيم")
    assert text == "حکیم"
    phone = sanitize_phone("۰۹۱۲۳۴۵۶۷۸۹")
    assert phone == "09123456789"


@pytest.mark.parametrize("value", [None, 5, "ناشناخته"])
def test_gender_rules(value) -> None:
    with pytest.raises(ValueError):
        normalize_gender(value)


@pytest.mark.parametrize("value", [None, 5, "خارج"])
def test_center_rules(value) -> None:
    with pytest.raises(ValueError):
        normalize_reg_center(value)


@pytest.mark.parametrize("value", [None, 7, "بی‌اثر"])
def test_status_rules(value) -> None:
    with pytest.raises(ValueError):
        normalize_reg_status(value)
