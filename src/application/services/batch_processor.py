# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable, Protocol

from src.application.commands.allocation import StartBatchAllocation
from src.application.services.allocation_service import AllocationService
from src.domain.shared.types import AllocationStatus


class JobStore(Protocol):
    def start(self, job_id: str, total: int) -> None: ...
    def update(self, job_id: str, processed: int, success: int, failed: int) -> None: ...
    def complete(self, job_id: str) -> None: ...
    def fail(self, job_id: str, reason: str) -> None: ...


class StudentBatchSource(Protocol):
    def count(self) -> int: ...
    def iter_chunks(self, chunk_size: int) -> Iterable[list]: ...


@dataclass(slots=True)
class BatchProcessor:
    service: AllocationService
    job_store: JobStore

    def run(self, cmd: StartBatchAllocation, source: StudentBatchSource, *, chunk_size: int = 1000) -> dict:
        total = source.count()
        job_id = cmd.job_id or f"job-{int(time.time())}"
        self.job_store.start(job_id, total)

        processed = 0
        success = 0
        failed = 0

        for chunk in source.iter_chunks(chunk_size):
            # Memory budget: ~30–60MB per 1k items; adjust chunk accordingly.
            for student in chunk:
                res = self.service.engine.select_best(student, self.service.mentors.find_candidates(student))
                if res.mentor_id is not None:
                    self.service.mentors.increment_load(res.mentor_id)
                    self.service.students.mark_assigned(student, res.mentor_id, status=AllocationStatus.OK)
                    success += 1
                else:
                    self.service.students.mark_assigned(student, None, status=AllocationStatus.NEEDS_NEW_MENTOR)
                    failed += 1
                processed += 1
            self.job_store.update(job_id, processed, success, failed)

        self.job_store.complete(job_id)
        return {"jobId": job_id, "processed": processed, "successful": success, "failed": failed}
