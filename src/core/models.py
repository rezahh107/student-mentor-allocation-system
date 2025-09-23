"""Data models used by the allocation engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(slots=True)
class Student:
    """Represents a student waiting for mentor assignment."""

    id: int
    gender: int
    grade_level: int
    center_id: int
    name: Optional[str] = None
    registration_status: Optional[int] = None
    academic_status: Optional[int] = None
    is_school_student: Optional[bool] = None


@dataclass(slots=True)
class Mentor:
    """Represents a mentor capable of supporting students."""

    id: int
    gender: int
    supported_grades: List[int]
    max_capacity: int
    current_students: int
    center_id: int
    primary_grade: Optional[int] = None
    name: Optional[str] = None
    speciality_tags: Optional[List[str]] = None

    def remaining_capacity(self) -> int:
        """Number of seats still available for this mentor."""
        return self.max_capacity - self.current_students
