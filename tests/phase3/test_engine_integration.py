from __future__ import annotations

from typing import List

import pytest

from src.phase3_allocation.contracts import AllocationConfig
from src.phase3_allocation.engine import AllocationEngine
from src.phase3_allocation.policy import EligibilityPolicy

from tests.phase3.conftest import (
    DictManagerCentersProvider,
    DictSpecialSchoolsProvider,
    DummyMentor,
    DummyStudent,
    special_provider,
)


def _make_engine(
    special: DictSpecialSchoolsProvider,
    manager: DictManagerCentersProvider,
    config: AllocationConfig | None = None,
) -> AllocationEngine:
    policy_obj = EligibilityPolicy(special, manager, config or AllocationConfig())
    return AllocationEngine(policy=policy_obj)


def test_engine_returns_none_when_no_candidates(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    best, trace = engine.evaluate(student, [])
    assert best is None
    assert trace == []


def test_engine_selects_lowest_occupancy_ratio(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    mentors: List[DummyMentor] = [
        DummyMentor(
            mentor_id=101,
            gender=0,
            allowed_groups=["A"],
            allowed_centers=[0],
            capacity=4,
            current_load=2,
            is_active=True,
            mentor_type="NORMAL",
        ),
        DummyMentor(
            mentor_id=102,
            gender=0,
            allowed_groups=["A"],
            allowed_centers=[0],
            capacity=4,
            current_load=1,
            is_active=True,
            mentor_type="NORMAL",
        ),
    ]
    best, trace = engine.evaluate(student, mentors)
    assert best is mentors[1]
    assert trace[1].ranking_key[0] == pytest.approx(0.25)


def test_engine_breaks_tie_with_current_load(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    mentors: List[DummyMentor] = [
        DummyMentor(101, 0, ["A"], [0], 4, 2, True, "NORMAL"),
        DummyMentor(102, 0, ["A"], [0], 6, 3, True, "NORMAL"),
    ]
    best, _ = engine.evaluate(student, mentors)
    assert best is mentors[0]


def test_engine_breaks_tie_with_mentor_id(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    mentors: List[DummyMentor] = [
        DummyMentor("200", 0, ["A"], [0], 4, 2, True, "NORMAL"),
        DummyMentor("150", 0, ["A"], [0], 4, 2, True, "NORMAL"),
    ]
    best, _ = engine.evaluate(student, mentors)
    assert best is mentors[1]


def test_engine_records_failure_trace(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="X", reg_center=0, reg_status=0)
    mentor = DummyMentor(101, 0, ["A"], [0], 4, 1, True, "NORMAL")
    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    assert trace[0].passed is False
    assert trace[0].trace[1]["code"] == "GROUP_ALLOWED"


def test_engine_fast_fail_truncates_trace(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    config = AllocationConfig(fast_fail=True)
    engine = _make_engine(special_provider, manager_provider, config)
    student = DummyStudent(gender=0, group_code="X", reg_center=0, reg_status=0)
    mentor = DummyMentor(101, 1, ["A"], [0], 4, 1, True, "NORMAL")
    _, trace = engine.evaluate(student, [mentor])
    assert len(trace[0].trace) == 1
    assert trace[0].trace[0]["code"] == "GENDER_MATCH"


def test_engine_trace_limit_applies(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    config = AllocationConfig(fast_fail=False, trace_limit_rejected=2)
    engine = _make_engine(special_provider, manager_provider, config)
    student = DummyStudent(gender=0, group_code="X", reg_center=2, reg_status=0)
    mentor = DummyMentor(101, 1, ["A"], [0], 1, 1, False, "SCHOOL")
    _, trace = engine.evaluate(student, [mentor])
    assert len(trace[0].trace) == 2


def test_engine_school_student_requires_school_mentor(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(
        gender=0,
        group_code="A",
        reg_center=0,
        reg_status=0,
        school_code=101,
        student_type=0,
        roster_year=1402,
    )
    mentor = DummyMentor(101, 0, ["A"], [0], 5, 1, True, "NORMAL")
    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    assert any(item["code"] == "SCHOOL_TYPE_COMPATIBLE" for item in trace[0].trace)


def test_engine_special_student_requires_matching_school_code(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(
        gender=0,
        group_code="A",
        reg_center=0,
        reg_status=0,
        school_code=999,
        student_type=1,
        roster_year=1402,
    )
    mentor = DummyMentor(101, 0, ["A"], [0], 5, 1, True, "SCHOOL")
    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    failures = [item for item in trace[0].trace if item["code"] == "SCHOOL_TYPE_COMPATIBLE"]
    assert failures and failures[0]["passed"] is False


def test_engine_manager_gate_missing_returns_reason(
    special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider
) -> None:
    engine = _make_engine(special_provider, manager_provider)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    mentor = DummyMentor(101, 0, ["A"], [0], 5, 1, True, "NORMAL", manager_id=99)
    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    manager_entries = [item for item in trace[0].trace if item["code"] == "MANAGER_CENTER_GATE"]
    assert manager_entries[0]["details"]["reason"] == "manager_centers_not_found"

