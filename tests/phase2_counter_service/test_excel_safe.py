# -*- coding: utf-8 -*-
from __future__ import annotations

import io
from typing import Iterator

import pytest

from src.infrastructure.export.excel_safe import (
    BOM_UTF8,
    make_excel_safe_writer,
    sanitize_cell,
    sanitize_row,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+1", "'+1"),
        ("-0", "'-0"),
        ("@cmd", "'@cmd"),
    ],
)
def test_sanitize_cell_guards_formula_injection(value: str, expected: str) -> None:
    assert sanitize_cell(value) == expected


def test_sanitize_cell_handles_none_and_digits() -> None:
    assert sanitize_cell(None) == ""
    assert sanitize_cell("۰۱۲۳") == "0123"
    assert sanitize_cell("\u200c123") == "123"
    assert sanitize_cell("  ") == "  "


def test_sanitize_cell_disable_guard() -> None:
    assert sanitize_cell("=SUM()", guard_formulas=False) == "=SUM()"


def test_sanitize_row_preserves_sequence() -> None:
    row = ["=A1", "123", None]
    assert sanitize_row(row) == ["'=A1", "123", ""]


def test_excel_safe_writer_bom_crlf_quote_all() -> None:
    buffer = io.StringIO()
    writer = make_excel_safe_writer(
        buffer,
        bom=True,
        guard_formulas=True,
        quote_all=True,
        crlf=True,
    )
    writer.writerow(["=1+1", "متن", "42"])
    payload = buffer.getvalue()
    assert payload.startswith(BOM_UTF8)
    assert "\r\n" in payload
    assert payload.endswith("\r\n")
    expected = "\"'=1+1\""
    assert expected in payload  # Quotes wrap the guarded value


def test_excel_safe_writer_streams_generator() -> None:
    buffer = io.StringIO()
    writer = make_excel_safe_writer(buffer, guard_formulas=True)
    count = 0

    def row_iter() -> Iterator[tuple[str, str]]:
        nonlocal count
        for index in range(2000):
            count += 1
            yield (f"ردیف-{index}", f"=SUM({index})")

    writer.writerows(row_iter())
    assert count == 2000
    output = buffer.getvalue().splitlines()
    assert len(output) == 2000
    first_fields = output[0].split(",")
    last_fields = output[-1].split(",")
    assert first_fields[1].startswith("'=")
    assert last_fields[1].startswith("'=")


def test_excel_safe_writer_quote_minimal() -> None:
    buffer = io.StringIO()
    writer = make_excel_safe_writer(buffer, guard_formulas=True, quote_all=False)
    writer.writerow(["کد", "=VALUE"])
    value = buffer.getvalue().strip()
    assert value.split(",")[0] == "کد"
    assert value.split(",")[1] == "'=VALUE"
