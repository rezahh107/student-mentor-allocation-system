from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class AcademicYearProvider:
    clock: Callable[[], float]

    def year_code(self) -> str:
        year = int(self.clock())
        return str(year)[-2:]
