# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AllocationError(Exception):
    error_code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.error_code}: {self.message}"


class CapacityExceededError(AllocationError):
    def __init__(self, mentor_id: int):
        super().__init__("CAPACITY_EXCEEDED", f"Mentor {mentor_id} has no remaining capacity")


class InvalidStudentDataError(AllocationError):
    def __init__(self, national_id: str, reason: str):
        super().__init__("INVALID_STUDENT_DATA", f"Student {national_id}: {reason}")


class MentorNotAvailableError(AllocationError):
    def __init__(self, national_id: str):
        super().__init__("MENTOR_NOT_AVAILABLE", f"No eligible mentor for student {national_id}")


class CounterGenerationError(AllocationError):
    def __init__(self, national_id: str, reason: str):
        super().__init__("COUNTER_GENERATION_FAILED", f"Counter generation failed for {national_id}: {reason}")


class ConcurrencyConflictError(AllocationError):
    def __init__(self, resource: str):
        super().__init__("CONCURRENCY_CONFLICT", f"Concurrency conflict on resource {resource}")

