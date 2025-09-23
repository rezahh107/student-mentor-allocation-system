"""Rules used to validate and prioritise mentor allocations."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Mentor, Student


@dataclass(slots=True)
class AllocationRules:
    """Encapsulates the business rules for pairing students with mentors."""

    capacity_weight: int = 10
    primary_grade_bonus: int = 100
    same_center_bonus: int = 50
    require_same_center: bool = False

    def can_assign(self, student: Student, mentor: Mentor) -> bool:
        """Return True when the mentor is allowed to take the student."""

        if student.gender != mentor.gender:
            return False

        if student.grade_level not in mentor.supported_grades:
            return False

        if mentor.current_students >= mentor.max_capacity:
            return False

        if self.require_same_center and student.center_id != mentor.center_id:
            return False

        return True

    def calculate_priority(self, student: Student, mentor: Mentor) -> int:
        """Compute a score that helps rank mentors for a student."""

        priority = 0

        if mentor.primary_grade is not None and student.grade_level == mentor.primary_grade:
            priority += self.primary_grade_bonus

        if student.center_id == mentor.center_id:
            priority += self.same_center_bonus

        remaining_capacity = mentor.remaining_capacity()
        if self.capacity_weight > 0 and remaining_capacity > 0:
            priority += remaining_capacity * self.capacity_weight

        return priority
