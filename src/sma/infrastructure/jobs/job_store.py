# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class JobStatusRec:
    total: int
    processed: int = 0
    successful: int = 0
    failed: int = 0
    status: str = "running"
    reason: str | None = None


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobStatusRec] = {}

    def start(self, job_id: str, total: int) -> None:
        self._jobs[job_id] = JobStatusRec(total=total, status="running")

    def update(self, job_id: str, processed: int, success: int, failed: int) -> None:
        rec = self._jobs[job_id]
        rec.processed = processed
        rec.successful = success
        rec.failed = failed

    def complete(self, job_id: str) -> None:
        rec = self._jobs[job_id]
        rec.status = "completed"

    def fail(self, job_id: str, reason: str) -> None:
        rec = self._jobs[job_id]
        rec.status = "failed"
        rec.reason = reason

    def get(self, job_id: str) -> JobStatusRec | None:
        return self._jobs.get(job_id)

