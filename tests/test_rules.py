# -*- coding: utf-8 -*-
from __future__ import annotations

from src.domain.allocation.engine import AllocationEngine
from src.domain.shared.types import Gender
from tests.factories import make_mentor, make_student


def test_normal_student_cannot_get_school_mentor():
    s = make_student("111", gender=Gender.male, group_code=101, school_code=None)
    m = make_mentor(1, gender=Gender.male, type="مدرسه", allowed_groups=[101])
    eng = AllocationEngine()
    res = eng.select_best(s, [m])
    assert res.mentor_id is None


def test_school_student_requires_school_code_match():
    s = make_student("222", school_code=123)
    m_ok = make_mentor(1, type="مدرسه", school_codes=[123])
    m_bad = make_mentor(2, type="مدرسه", school_codes=[999])
    eng = AllocationEngine()
    res = eng.select_best(s, [m_bad, m_ok])
    assert res.mentor_id == 1


def test_gender_mismatch_rejected():
    s = make_student("333", gender=Gender.female)
    m = make_mentor(1, gender=Gender.male)
    eng = AllocationEngine()
    res = eng.select_best(s, [m])
    assert res.mentor_id is None

