# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Iterable

from sma.domain.mentor.entities import Mentor
from sma.domain.shared.types import EduStatus, Gender, RegCenter, RegStatus, StudentType
from sma.domain.student.entities import Student


def make_student(
    national_id: str = "0012345678",
    *,
    gender: Gender = Gender.male,
    edu_status: EduStatus = EduStatus.student,
    reg_center: RegCenter = RegCenter.center0,
    reg_status: RegStatus = RegStatus.status1,
    group_code: int = 101,
    school_code: int | None = None,
) -> Student:
    return Student(
        national_id=national_id,
        gender=gender,
        edu_status=edu_status,
        reg_center=reg_center,
        reg_status=reg_status,
        group_code=group_code,
        school_code=school_code,
        student_type=StudentType.school if school_code is not None else StudentType.normal,
    )


def make_mentor(
    mentor_id: int = 1,
    *,
    gender: Gender = Gender.male,
    type: str = "عادی",
    capacity: int = 60,
    current_load: int = 0,
    allowed_groups: Iterable[int] = (101,),
    allowed_centers: Iterable[int] = (0,),
    school_codes: Iterable[int] | None = None,
) -> Mentor:
    m = Mentor(
        mentor_id=mentor_id,
        name=None,
        gender=gender,
        type=type,
        capacity=capacity,
        current_load=current_load,
    )
    m.allowed_groups.update(allowed_groups)
    m.allowed_centers.update(allowed_centers)
    if school_codes:
        m.school_codes.update(school_codes)
    return m

