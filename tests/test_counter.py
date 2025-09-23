# -*- coding: utf-8 -*-
from __future__ import annotations

from src.domain.counter.value_objects import Counter
from src.domain.shared.types import Gender


def test_counter_format():
    c = Counter.build("04", Gender.male, 42)
    assert c.value == "043570042"

