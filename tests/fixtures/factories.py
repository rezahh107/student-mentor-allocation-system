from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import List

from src.api.models import MentorDTO, StudentDTO, validate_national_code


def _gen_valid_melli(rng: random.Random) -> str:
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if len(set(base)) == 1:
            continue
        checksum = sum(int(base[i]) * (10 - i) for i in range(9))
        r = checksum % 11
        check = r if r < 2 else 11 - r
        code = f"{base}{check}"
        if validate_national_code(code):
            return code


def make_student(student_id: int, gender: int = 1, center: int = 1, school: bool = False, level: str = "konkoori") -> StudentDTO:
    rng = random.Random(1234 + student_id)
    first = "علی" if gender == 1 else "فاطمه"
    last = "احمدی"
    created = datetime.utcnow() - timedelta(days=rng.randint(0, 120))
    return StudentDTO(
        student_id=student_id,
        counter=f"{datetime.utcnow().year % 100:02d}{373 if gender==1 else 357}{student_id:04d}",
        first_name=first,
        last_name=last,
        national_code=_gen_valid_melli(rng),
        phone="+98912" + "".join(str(rng.randint(0, 9)) for _ in range(7)),
        birth_date=(datetime.utcnow() - timedelta(days=365 * rng.randint(16, 25))).date(),
        gender=gender,  # type: ignore[arg-type]
        education_status=1,
        registration_status=0,
        center=center,  # type: ignore[arg-type]
        grade_level=level,
        school_type="school" if school else "normal",  # type: ignore[arg-type]
        school_code=("SCH-1001" if school else None),
        created_at=created,
        updated_at=created,
        allocation_status=None,
    )


def make_mentor(mentor_id: int, gender: int = 1, capacity: int = 60, current: int = 0, school: bool = False, centers: List[int] | None = None, groups: List[str] | None = None) -> MentorDTO:
    return MentorDTO(
        id=mentor_id,
        name=f"منتور {mentor_id}",
        gender=gender,  # type: ignore[arg-type]
        capacity=capacity,
        current_load=current,
        allowed_groups=groups or ["konkoori", "motavassete2", "motavassete1"],
        allowed_centers=centers or [1, 2, 3],
        is_school_mentor=school,
        school_codes=["SCH-1001"] if school else [],
        is_active=True,
    )

