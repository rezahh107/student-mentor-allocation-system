# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.domain.counter.value_objects import Counter
from src.domain.shared.types import Gender
from src.domain.student.entities import Student


class CounterRepository(Protocol):
    def get_last_seq(self, year_two_digits: str, gender_code: str) -> int: ...
    def reserve_next(self, year_two_digits: str, gender_code: str) -> int: ...


@dataclass(slots=True)
class CounterService:
    repo: CounterRepository

    def generate(self, student: Student, year_two_digits: str) -> Counter:
        # Reuse if already present
        if student.counter:
            return Counter(student.counter)
        seq = self.repo.reserve_next(year_two_digits, student.gender.counter_code)
        return Counter.build(year_two_digits, student.gender, seq)

