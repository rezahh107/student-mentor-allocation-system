from dataclasses import dataclass
from typing import Iterable, List

from sma.application.commands.allocation import StartBatchAllocation
from sma.application.services.allocation_service import AllocationService
from sma.domain.allocation.engine import AllocationEngine
from sma.domain.allocation.fairness import FairnessConfig, FairnessStrategy
from sma.domain.mentor.entities import Mentor
from sma.domain.shared.events import DomainEvent
from sma.domain.shared.types import AllocationStatus, EduStatus, Gender, RegCenter, RegStatus, StudentType
from sma.domain.student.entities import Student


@dataclass
class _StudentRepo:
    items: List[Student]

    def list_ready_for_allocation(self, batch_size: int = 1000) -> Iterable[Student]:  # noqa: D401
        return list(self.items)

    def mark_assigned(self, student: Student, mentor_id: int | None, status: AllocationStatus) -> None:  # noqa: D401
        pass


@dataclass
class _MentorRepo:
    mentors: List[Mentor]

    def find_candidates(self, student: Student) -> Iterable[Mentor]:  # noqa: D401
        return list(self.mentors)

    def increment_load(self, mentor_id: int) -> None:  # noqa: D401
        for mentor in self.mentors:
            if mentor.mentor_id == mentor_id:
                mentor.current_load += 1


class _Outbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def enqueue(self, *events: DomainEvent) -> None:
        self.events.extend(events)


def _student(group: int) -> Student:
    return Student(
        national_id=f"{group:010d}",
        gender=Gender.male,
        edu_status=EduStatus.student,
        reg_center=RegCenter.center0,
        reg_status=RegStatus.status1,
        group_code=group,
        student_type=StudentType.normal,
        counter="250000000",
    )


def _mentor(mid: int, *, allowed_groups: set[int]) -> Mentor:
    return Mentor(
        mentor_id=mid,
        name=None,
        gender=Gender.male,
        type="عادی",
        capacity=5,
        current_load=0,
        allowed_groups=allowed_groups,
        allowed_centers={0},
    )


def test_allocation_service_emits_reason_payloads() -> None:
    students = [_student(10), _student(99)]
    mentors = [_mentor(1, allowed_groups={10})]
    outbox = _Outbox()
    service = AllocationService(
        students=_StudentRepo(students),
        mentors=_MentorRepo(mentors),
        engine=AllocationEngine(fairness=FairnessConfig(strategy=FairnessStrategy.DETERMINISTIC_JITTER)),
        outbox=outbox,
    )

    service.start_batch_allocation(StartBatchAllocation(priority_mode="normal", guarantee_assignment=False))
    assert len(outbox.events) == 2
    assigned, failed = outbox.events
    assert assigned.payload["fairness_strategy"] == FairnessStrategy.DETERMINISTIC_JITTER.value
    assert assigned.payload["fairness_key"] == "250000000"[:2]
    trace = [entry["code"] if entry else None for entry in assigned.payload["rule_trace"]]
    assert "CAPACITY_FULL" not in trace  # success path should not include failures

    assert failed.payload["reason_code"] == "NO_ELIGIBLE_MENTOR"
    assert failed.payload["fairness_strategy"] == FairnessStrategy.DETERMINISTIC_JITTER.value
    assert failed.payload["fairness_key"] == "250000000"[:2]
    assert "مربی" in failed.payload["reason_message"]
