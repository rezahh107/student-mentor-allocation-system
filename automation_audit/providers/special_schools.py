from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class SpecialSchoolsRoster:
    year: str
    mapping: Dict[str, str]

    def student_type(self, student_id: str) -> str:
        return self.mapping.get(student_id, "unknown")
