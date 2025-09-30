# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.domain.shared.types import Gender, EduStatus, StudentType, RegCenter, RegStatus
from src.domain.student.mobile import normalize_mobile


@dataclass(slots=True)
class Student:
    national_id: str
    gender: Gender
    edu_status: EduStatus
    reg_center: RegCenter
    reg_status: RegStatus
    group_code: int
    school_code: Optional[int] = None
    student_type: StudentType = StudentType.normal
    counter: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None

    def __post_init__(self) -> None:
        normalized = normalize_mobile(self.mobile)
        self.mobile = normalized

