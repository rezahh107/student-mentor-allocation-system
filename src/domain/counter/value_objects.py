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
        """ساخت شمارنده ۹ رقمی با کنترل خطاهای متداول."""

        if len(year_two_digits) != 2 or not year_two_digits.isdigit():
            raise RuntimeError("کد سال باید دقیقا دو رقم معتبر باشد")
        if not isinstance(gender, Gender):
            raise RuntimeError("کد جنسیت برای شمارنده معتبر نیست")
        if not 0 <= seq <= 9999:
            raise RuntimeError("توالی شمارنده باید بین 0 تا 9999 باشد")

        tail = f"{seq:04d}"
        code = gender.counter_code
        value = f"{year_two_digits}{code}{tail}"
        if len(value) != Counter._len:
            raise RuntimeError("طول شمارنده از ۹ رقم فراتر رفت")
        return Counter(value)

