from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sma.phase6_import_to_sabt.normalization import fold_digits, normalize_phone, normalize_text


@pytest.fixture(name="clean_state")
def fixture_clean_state(tmp_path: Path) -> tuple[Path, Path]:
    sandbox = tmp_path / uuid.uuid4().hex
    sandbox.mkdir()
    before_snapshot = sorted(sandbox.iterdir())
    yield sandbox, Path(tmp_path)
    for child in sandbox.iterdir():
        child.unlink()
    sandbox.rmdir()
    after_snapshot = sorted(tmp_path.iterdir())
    assert before_snapshot == [], f"Sandbox not empty: {after_snapshot}"


def debug_context(sandbox: Path) -> dict[str, object]:
    return {"sandbox": sandbox.as_posix(), "files": sorted(p.name for p in sandbox.iterdir())}


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        (0, "0"),
        ("0", "0"),
        ("", ""),
        ("   ", ""),
        ("\u200c۱۲۳", "123"),
        ("very" * 1000, "very" * 1000),
    ],
)
def test_normalize_text_variants(clean_state: tuple[Path, Path], raw: object | None, expected: str) -> None:
    sandbox, _ = clean_state
    result = normalize_text(raw)
    assert result == expected, debug_context(sandbox)


def test_mixed_digits_and_zw(clean_state: tuple[Path, Path]) -> None:
    sandbox, _ = clean_state
    text = "کد \u200dمرکز ٠١٢۳٤۵۶۷٨۹"
    normalized = normalize_text(text)
    assert normalized == "کد مرکز 0123456789", debug_context(sandbox)


def test_phone_normalization_and_digit_folding(clean_state: tuple[Path, Path]) -> None:
    sandbox, _ = clean_state
    phone = "۰۹-۱۲۳\u200c۴۵۶۷۸"
    normalized = normalize_phone(phone)
    assert normalized == "0912345678", debug_context(sandbox)
    folded = fold_digits("۰۹۱۲۳۶۷۷۷۷")
    assert folded == "0912367777", debug_context(sandbox)
