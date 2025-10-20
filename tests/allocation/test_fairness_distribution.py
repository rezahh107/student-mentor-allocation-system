from collections import Counter

from sma.domain.allocation.engine import AllocationEngine
from sma.domain.allocation.fairness import FairnessConfig, FairnessStrategy
from sma.domain.mentor.entities import Mentor
from sma.domain.shared.types import EduStatus, Gender, RegCenter, RegStatus, StudentType
from sma.domain.student.entities import Student


def _student() -> Student:
    return Student(
        national_id="0012345678",
        gender=Gender.male,
        edu_status=EduStatus.student,
        reg_center=RegCenter.center0,
        reg_status=RegStatus.status1,
        group_code=5,
        student_type=StudentType.normal,
        counter="250000000",
    )


def _mentor(mid: int, *, load: int, capacity: int) -> Mentor:
    return Mentor(
        mentor_id=mid,
        name=None,
        gender=Gender.male,
        type="عادی",
        capacity=capacity,
        current_load=load,
        allowed_groups={5},
        allowed_centers={0},
    )


def test_no_starvation_under_skew() -> None:
    engine = AllocationEngine(
        fairness=FairnessConfig(strategy=FairnessStrategy.BUCKET_ROUND_ROBIN, bucket_size=0.2)
    )
    mentors = [
        _mentor(1, load=0, capacity=10),
        _mentor(2, load=3, capacity=10),
        _mentor(3, load=6, capacity=12),
    ]
    student = _student()
    selections: Counter[int] = Counter()
    for _ in range(12):
        result = engine.select_best(student, mentors, academic_year="25")
        assert result.mentor_id is not None
        selections[result.mentor_id] += 1
        for mentor in mentors:
            if mentor.mentor_id == result.mentor_id:
                mentor.current_load += 1
    assert set(selections.keys()) == {1, 2, 3}


def test_fairness_determinism() -> None:
    mentors = [
        _mentor(1, load=2, capacity=12),
        _mentor(2, load=2, capacity=12),
        _mentor(3, load=3, capacity=12),
    ]
    student = _student()
    engine_a = AllocationEngine(fairness=FairnessConfig(strategy=FairnessStrategy.DETERMINISTIC_JITTER))
    engine_b = AllocationEngine(fairness=FairnessConfig(strategy=FairnessStrategy.DETERMINISTIC_JITTER))
    result_a = engine_a.select_best(student, mentors, academic_year="25")
    result_b = engine_b.select_best(student, list(reversed(mentors)), academic_year="25")
    assert result_a.mentor_id == result_b.mentor_id
    assert result_a.fairness_key == result_b.fairness_key == "25"
