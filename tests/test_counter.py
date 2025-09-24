# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from src.domain.counter.value_objects import Counter
from src.domain.shared.types import Gender


def test_counter_format():
    c = Counter.build("04", Gender.male, 42)
    assert c.value == "043570042"


def test_counter_build_invalid_year_raises() -> None:
    with pytest.raises(RuntimeError, match="کد سال"):
        Counter.build("4", Gender.female, 1)


def test_counter_build_invalid_sequence_raises() -> None:
    with pytest.raises(RuntimeError, match="توالی"):
        Counter.build("04", Gender.male, 10000)

