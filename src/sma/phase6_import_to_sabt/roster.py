from __future__ import annotations

from typing import Iterable, Set

from sma.phase6_import_to_sabt.models import SpecialSchoolsRoster


class InMemoryRoster(SpecialSchoolsRoster):
    def __init__(self, mapping: dict[int, Iterable[int]]):
        self.mapping = {year: {int(code) for code in codes} for year, codes in mapping.items()}

    def is_special(self, year: int, school_code: int | None) -> bool:
        if school_code is None:
            return False
        return int(school_code) in self.mapping.get(year, set())
