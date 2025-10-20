from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sma.phase6_import_to_sabt.sanitization import always_quote, fold_digits, guard_formula


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_excel_contract_intact_after_packaging(tmp_path, clean_state):
    values = ["=SUM(A1:A2)", "+1", "۱۲۳۴", "plain"]
    guarded = [guard_formula(value) for value in values]
    digits = fold_digits(values[2])
    assert guarded[0].startswith("'")
    assert guarded[1].startswith("'")
    assert digits == "1234"

    target = tmp_path / "export.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow([always_quote(value) for value in guarded])
    data = target.read_bytes()
    assert data.endswith(b"\r\n")
