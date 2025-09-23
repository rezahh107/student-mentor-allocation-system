# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Optional


class Gender(IntEnum):
    male = 0
    female = 1

    @property
    def counter_code(self) -> str:
        return "357" if self is Gender.male else "373"


class EduStatus(IntEnum):
    graduate = 0
    student = 1


class StudentType(IntEnum):
    normal = 0
    school = 1


class RegCenter(IntEnum):
    center0 = 0
    center1 = 1
    center2 = 2


class RegStatus(IntEnum):
    status0 = 0
    status1 = 1
    status3 = 3


class AllocationStatus(StrEnum):
    OK = "OK"
    TEMP_REVIEW = "TEMP_REVIEW"
    NEEDS_NEW_MENTOR = "NEEDS_NEW_MENTOR"


@dataclass(slots=True)
class RuleResult:
    ok: bool
    reason: Optional[str] = None

