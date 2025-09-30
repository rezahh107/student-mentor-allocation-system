from src.domain.allocation.engine import AllocationEngine
from src.domain.allocation.fairness import FairnessConfig, FairnessStrategy
from src.domain.allocation.reasons import ReasonCode, build_reason
from src.domain.mentor.entities import Mentor
from src.domain.shared.types import EduStatus, Gender, RegCenter, RegStatus, StudentType
from src.domain.student.entities import Student


def _student() -> Student:
    return Student(
        national_id="0012345678",
        gender=Gender.male,
        edu_status=EduStatus.student,
        reg_center=RegCenter.center0,
        reg_status=RegStatus.status1,
        group_code=10,
        student_type=StudentType.normal,
        counter="250000000",
    )


def _mentor(mid: int, *, capacity: int, load: int) -> Mentor:
    return Mentor(
        mentor_id=mid,
        name=None,
        gender=Gender.male,
        type="عادی",
        capacity=capacity,
        current_load=load,
        allowed_groups={10},
        allowed_centers={0},
    )


def test_codes_stable_and_localized() -> None:
    expected = {
        ReasonCode.OK,
        ReasonCode.GENDER_MISMATCH,
        ReasonCode.GROUP_NOT_ALLOWED,
        ReasonCode.CENTER_NOT_ALLOWED,
        ReasonCode.CAPACITY_FULL,
        ReasonCode.GRADUATE_SCHOOL_FORBIDDEN,
        ReasonCode.SCHOOL_STUDENT_NEEDS_SCHOOL_MENTOR,
        ReasonCode.SCHOOL_CODE_MISMATCH,
        ReasonCode.NORMAL_STUDENT_CANNOT_GET_SCHOOL_MENTOR,
        ReasonCode.NO_ELIGIBLE_MENTOR,
    }
    assert set(ReasonCode) == expected
    for code in ReasonCode:
        message = build_reason(code).message_fa
        assert message


def test_engine_outputs_reason_trace() -> None:
    engine = AllocationEngine(fairness=FairnessConfig(strategy=FairnessStrategy.NONE))
    student = _student()
    mentors = [_mentor(1, capacity=1, load=1)]
    result = engine.select_best(student, mentors, academic_year="25")
    assert result.mentor_id is None
    assert result.reason is not None
    assert result.reason.code == ReasonCode.NO_ELIGIBLE_MENTOR
    trace_codes = [entry.code if entry else None for entry in result.rule_trace]
    assert ReasonCode.CAPACITY_FULL in trace_codes
