# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from src.application.commands.allocation import GetJobStatus, StartBatchAllocation
from src.domain.allocation.engine import AllocationEngine
from src.domain.mentor.entities import Mentor
from src.domain.shared.events import AllocationFailed, MentorAssigned
from src.domain.shared.types import AllocationStatus
from src.domain.student.entities import Student


class StudentRepository(Protocol):
    def list_ready_for_allocation(self, batch_size: int = 1000) -> Iterable[Student]: ...
    def mark_assigned(self, student: Student, mentor_id: int | None, status: AllocationStatus) -> None: ...


class MentorRepository(Protocol):
    def find_candidates(self, student: Student) -> Iterable[Mentor]: ...
    def increment_load(self, mentor_id: int) -> None: ...


class Outbox(Protocol):
    def enqueue(self, *events) -> None: ...


@dataclass(slots=True)
class AllocationService:
    students: StudentRepository
    mentors: MentorRepository
    engine: AllocationEngine
    outbox: Outbox

    def start_batch_allocation(self, cmd: StartBatchAllocation) -> dict:
        processed = 0
        success = 0
        for s in self.students.list_ready_for_allocation():
            processed += 1
            candidates = list(self.mentors.find_candidates(s))
            result = self.engine.select_best(s, candidates)
            if result.mentor_id is not None:
                self.mentors.increment_load(result.mentor_id)
                self.students.mark_assigned(s, result.mentor_id, AllocationStatus.OK)
                self.outbox.enqueue(MentorAssigned(national_id=s.national_id, mentor_id=result.mentor_id, rule_trace=result.rule_trace))
                success += 1
            else:
                self.students.mark_assigned(s, None, AllocationStatus.NEEDS_NEW_MENTOR)
                self.outbox.enqueue(AllocationFailed(national_id=s.national_id, reason="NoEligibleMentor"))
        return {"processed": processed, "successful": success}

    def get_job_status(self, q: GetJobStatus) -> dict:
        # Placeholder; integrate with job store when implemented
        return {"jobId": q.job_id, "status": "completed", "progress": 100}

