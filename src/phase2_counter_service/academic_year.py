"""Academic year code provider used by the counter runtime."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Mapping

from src.core.normalize import normalize_digits


def _strip_zw(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) not in {0x200c, 0x200d, 0x200e, 0x200f})


@dataclass(slots=True)
class AcademicYearProvider:
    """Resolve canonical two-digit year codes for roster operations."""

    code_map: Mapping[str, str]

    def code_for(self, year: str | int) -> str:
        """Return the canonical year code for the provided input."""

        raw = str(year) if year is not None else ""
        normalized = normalize_digits(unicodedata.normalize("NFKC", raw))
        normalized = _strip_zw(normalized).strip()
        if not normalized or not normalized.isdigit():
            raise ValueError("سال نامعتبر است")
        if normalized in self.code_map:
            code = self.code_map[normalized]
        else:
            if len(normalized) < 4:
                raise ValueError("سال نامعتبر است")
            code = normalized[-2:]
        code = normalize_digits(unicodedata.normalize("NFKC", code))
        code = _strip_zw(code).strip()
        if not code.isdigit() or len(code) != 2:
            raise ValueError("کد سال نامعتبر است")
        return code


__all__ = ["AcademicYearProvider"]
