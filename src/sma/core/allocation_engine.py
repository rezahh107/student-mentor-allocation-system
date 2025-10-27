"""Core allocation engine responsible for pairing students with mentors."""
from __future__ import annotations

from typing import Dict, List, Optional

from .allocation_rules import AllocationRules
from .models import Mentor, Student


class AllocationEngine:
    """High-level coordinator that applies rules to build assignments."""

    def __init__(self, rules: Optional[AllocationRules] = None) -> None:
        self.rules = rules or AllocationRules()
        self.assignments: List[Dict[str, int]] = []
        self.failed_assignments: List[Dict[str, str]] = []

    def allocate_students(self, students: List[Student], mentors: List[Mentor]) -> Dict[str, object]:
        """Allocate each student to the most suitable mentor available."""

        results: Dict[str, object] = {
            "successful": 0,
            "failed": 0,
            "assignments": [],
            "errors": [],
        }

        for student in students:
            mentor = self._find_best_mentor(student, mentors)
            if mentor:
                priority = self.rules.calculate_priority(student, mentor)
                assignment = self._assign_student(student, mentor, priority)
                results["successful"] += 1
                results["assignments"].append(assignment)
            else:
                reason = self._get_failure_reason(student, mentors)
                failed = {"student_id": student.id, "reason": reason}
                self.failed_assignments.append(failed)
                results["failed"] += 1
                results["errors"].append(failed)

        return results

    def reset(self) -> None:
        """Clear cached allocation state so the engine can be reused."""

        self.assignments.clear()
        self.failed_assignments.clear()

    def _find_best_mentor(self, student: Student, mentors: List[Mentor]) -> Optional[Mentor]:
        """Return the highest ranked mentor that can accept the student."""

        best: Optional[Mentor] = None
        best_score = -1

        for mentor in mentors:
            if not self.rules.can_assign(student, mentor):
                continue

            score = self.rules.calculate_priority(student, mentor)
            if score > best_score:
                best = mentor
                best_score = score
                continue

            if best is None or score != best_score:
                continue

            # Tie-breaker to keep the distribution balanced and deterministic.
            if mentor.current_students < best.current_students:
                best = mentor
            elif (
                mentor.current_students == best.current_students
                and mentor.remaining_capacity() > best.remaining_capacity()
            ):
                best = mentor
            elif (
                mentor.current_students == best.current_students
                and mentor.remaining_capacity() == best.remaining_capacity()
                and mentor.id < best.id
            ):
                best = mentor

        return best

    def _assign_student(self, student: Student, mentor: Mentor, priority: int) -> Dict[str, int]:
        """Persist the assignment and update mentor load."""

        mentor.current_students += 1
        assignment = {
            "student_id": student.id,
            "mentor_id": mentor.id,
            "priority_score": priority,
        }
        self.assignments.append(assignment)
        return assignment

    def _get_failure_reason(self, student: Student, mentors: List[Mentor]) -> str:
        """Explain why a student could not be assigned."""

        if not mentors:
            return "no mentors available"

        matching_gender = [m for m in mentors if m.gender == student.gender]
        if not matching_gender:
            return "no mentor with matching gender"

        matching_grade = [
            m for m in matching_gender if student.grade_level in m.supported_grades
        ]
        if not matching_grade:
            return "grade level not supported"

        capacity_left = [m for m in matching_grade if m.current_students < m.max_capacity]
        if not capacity_left:
            return "no capacity available"

        return "no mentor matched"
