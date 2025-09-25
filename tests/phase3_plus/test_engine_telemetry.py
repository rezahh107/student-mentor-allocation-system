from __future__ import annotations

from src.observe.perf import PerformanceObserver
from src.phase3_allocation.contracts import AllocationConfig
from src.phase3_allocation.engine import AllocationEngine
from src.phase3_allocation.policy import EligibilityPolicy

from tests.phase3.conftest import DummyMentor, DummyStudent, DictManagerCentersProvider, DictSpecialSchoolsProvider


def _make_policy() -> EligibilityPolicy:
    special = DictSpecialSchoolsProvider({1402: frozenset({101, 202})})
    manager = DictManagerCentersProvider({10: frozenset({0, 1})})
    return EligibilityPolicy(special, manager, AllocationConfig())


def test_counters_increment_for_passes() -> None:
    observer = PerformanceObserver()
    engine = AllocationEngine(policy=_make_policy(), observer=observer)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    mentor = DummyMentor(
        mentor_id=101,
        gender=0,
        allowed_groups=["A"],
        allowed_centers=[0],
        capacity=4,
        current_load=1,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=10,
    )
    engine.evaluate(student, [mentor])
    counters = observer.counters_snapshot()
    for code in [
        "GENDER_MATCH",
        "GROUP_ALLOWED",
        "CENTER_ALLOWED",
        "REG_STATUS_ALLOWED",
        "CAPACITY_AVAILABLE",
        "SCHOOL_TYPE_COMPATIBLE",
        "GRADUATE_NOT_TO_SCHOOL",
        "MANAGER_CENTER_GATE",
    ]:
        key = f'allocation_policy_pass_total{{rule="{code}"}}'
        assert counters.get(key, 0) >= 1


def test_no_candidate_counter_increments() -> None:
    observer = PerformanceObserver()
    engine = AllocationEngine(policy=_make_policy(), observer=observer)
    student = DummyStudent(gender=0, group_code="Z", reg_center=0, reg_status=0)
    mentor = DummyMentor(
        mentor_id=101,
        gender=0,
        allowed_groups=["A"],
        allowed_centers=[0],
        capacity=4,
        current_load=1,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=10,
    )
    engine.evaluate(student, [mentor])
    counters = observer.counters_snapshot()
    assert counters.get("allocation_no_candidate_total") == 1


def test_normalization_failure_counter() -> None:
    observer = PerformanceObserver()
    engine = AllocationEngine(policy=_make_policy(), observer=observer)
    student = DummyStudent(gender=0, group_code="A", reg_center=0, reg_status=0)
    bad_mentor = DummyMentor(
        mentor_id=101,
        gender=0,
        allowed_groups=["A"],
        allowed_centers=[99],  # invalid center triggers normalization error
        capacity=4,
        current_load=1,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=10,
    )
    engine.evaluate(student, [bad_mentor])
    counters = observer.counters_snapshot()
    assert counters.get('allocation_policy_failure_total{stage="normalization"}') == 1
