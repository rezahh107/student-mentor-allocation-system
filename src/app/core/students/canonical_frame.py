from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

CANONICAL_STUDENT_COLUMNS: tuple[str, ...] = (
    "student_id",
    "national_id",
    "first_name",
    "last_name",
    "gender_code",
    "graduation_status_code",
    "education_level",
    "grade_level",
    "group_code",
)


@dataclass
class StudentCanonicalFrame:
    """Container for canonicalized student data.

    The frame must include all ``CANONICAL_STUDENT_COLUMNS`` with domain-level
    meanings aligned to the Technical SSoT. ``education_level``,
    ``grade_level``, and ``group_code`` are intentionally kept distinct to
    avoid conflating group semantics with academic progression.
    """

    frame: pd.DataFrame

    @classmethod
    def ensure_schema(cls, df: pd.DataFrame) -> "StudentCanonicalFrame":
        """Return a canonical frame with all expected columns present.

        Missing columns are added with ``pd.NA`` to keep downstream validation
        deterministic. Extraneous columns are preserved to avoid silent drops.
        """

        filled = df.copy()
        for column in CANONICAL_STUDENT_COLUMNS:
            if column not in filled.columns:
                filled[column] = pd.NA
        return cls(filled)

    @staticmethod
    def required_columns() -> Iterable[str]:
        return CANONICAL_STUDENT_COLUMNS
