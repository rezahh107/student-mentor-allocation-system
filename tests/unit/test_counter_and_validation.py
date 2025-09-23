from __future__ import annotations

import asyncio
import random

import pytest

from src.api.mock_data import MockBackend
from src.api.models import validate_iranian_phone, validate_national_code


def test_counter_format():
    backend = MockBackend()
    c_m = asyncio.get_event_loop().run_until_complete(backend.get_next_counter(1))
    c_f = asyncio.get_event_loop().run_until_complete(backend.get_next_counter(0))
    assert len(c_m) == 9 and len(c_f) == 9
    assert c_m[2:5] == "373"
    assert c_f[2:5] == "357"


@pytest.mark.asyncio
async def test_counter_concurrency_uniqueness():
    backend = MockBackend()
    async def get_one():
        g = random.choice([0, 1])
        return await backend.get_next_counter(g)
    vals = await asyncio.gather(*[get_one() for _ in range(200)])
    assert len(vals) == len(set(vals))


def test_validate_national_code_and_phone():
    # A valid Iranian mobile
    assert validate_iranian_phone("09123456789")
    assert validate_iranian_phone("+989123456789")
    # Invalid
    assert not validate_iranian_phone("00123")

    # National code: generate a valid one from backend helper by creating students
    backend = MockBackend()
    s = backend._students[0]
    assert validate_national_code(s.national_code)

    # Persian digits normalization (local helper)
    persian = "۱۲۳۴۵۶۷۸۹۰"
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    assert persian.translate(trans) == "1234567890"

