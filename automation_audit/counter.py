from __future__ import annotations

import re
from dataclasses import dataclass

from .providers.academic_year import AcademicYearProvider

COUNTER_RE = re.compile(r"^\d{2}(357|373)\d{4}$")
PREFIX_BY_GENDER = {0: "373", 1: "357"}


@dataclass
class CounterBuilder:
    year_provider: AcademicYearProvider

    def build(self, gender: int, sequence: int) -> str:
        prefix = PREFIX_BY_GENDER[gender]
        year = self.year_provider.year_code()
        value = f"{year}{prefix}{sequence:04d}"
        if not COUNTER_RE.fullmatch(value):
            raise ValueError("شناسه شمارنده نامعتبر است.")
        return value
