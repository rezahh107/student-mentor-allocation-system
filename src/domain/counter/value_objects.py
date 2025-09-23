# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.domain.shared.types import Gender


@dataclass(frozen=True, slots=True)
class Counter:
    """9-digit student counter: YY + (357|373) + ####"""

    value: str
    _len: ClassVar[int] = 9

    @staticmethod
    def build(year_two_digits: str, gender: Gender, seq: int) -> "Counter":
        assert len(year_two_digits) == 2 and year_two_digits.isdigit()
        code = gender.counter_code
        assert 0 <= seq <= 9999
        tail = f"{seq:04d}"
        val = f"{year_two_digits}{code}{tail}"
        if len(val) != Counter._len:
            raise ValueError("Invalid counter length")
        return Counter(val)

