from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional

from faker import Faker

from ...core.models import Mentor, Student


class IBackendService(ABC):
    """Abstract contract for allocation backend services."""

    @abstractmethod
    async def get_unassigned_students(self, filters: Optional[Dict] = None) -> List[Student]:
        """Return students that still need a mentor."""

    @abstractmethod
    async def get_available_mentors(self, filters: Optional[Dict] = None) -> List[Mentor]:
        """Return mentors that can accept additional students."""

    @abstractmethod
    async def save_allocation_results(self, results: Dict) -> bool:
        """Persist the allocation results."""

    @abstractmethod
    async def get_allocation_statistics(self) -> Dict:
        """Return overall system statistics."""


class MockBackendService(IBackendService):
    """Simple in-memory backend used for tests and demos."""

    def __init__(self, *, student_count: int = 150, mentor_count: int = 25) -> None:
        self._faker = Faker("fa_IR")
        self.students: List[Student] = self._generate_sample_students(student_count)
        self.mentors: List[Mentor] = self._generate_sample_mentors(mentor_count)
        self.assignments: List[Dict[str, object]] = []
        self._lock = asyncio.Lock()

    async def get_unassigned_students(self, filters: Optional[Dict] = None) -> List[Student]:
        async with self._lock:
            unassigned = [s for s in self.students if not self._is_assigned(s.id)]
        return self._apply_student_filters(unassigned, filters)

    async def get_available_mentors(self, filters: Optional[Dict] = None) -> List[Mentor]:
        async with self._lock:
            available = [m for m in self.mentors if m.remaining_capacity() > 0]
        return self._apply_mentor_filters(available, filters)

    async def save_allocation_results(self, results: Dict) -> bool:
        assignments = results.get("assignments", [])
        async with self._lock:
            for assignment in assignments:
                record = {
                    "student_id": assignment["student_id"],
                    "mentor_id": assignment["mentor_id"],
                    "assigned_at": datetime.now(),
                    "priority_score": assignment.get("priority_score", 0),
                }
                self.assignments.append(record)
                mentor = self._find_mentor(assignment["mentor_id"])
                if mentor:
                    mentor.current_students += 1
        return True

    async def get_allocation_statistics(self) -> Dict:
        async with self._lock:
            total_students = len(self.students)
            assigned_students = len({item["student_id"] for item in self.assignments})
            total_mentors = len(self.mentors)
            total_capacity = sum(m.max_capacity for m in self.mentors)
            used_capacity = sum(m.current_students for m in self.mentors)

        available_capacity = max(total_capacity - used_capacity, 0)
        utilization_rate = (
            round((used_capacity / total_capacity) * 100, 1) if total_capacity > 0 else 0
        )

        return {
            "total_students": total_students,
            "assigned_students": assigned_students,
            "unassigned_students": total_students - assigned_students,
            "total_mentors": total_mentors,
            "active_mentors": len([m for m in self.mentors if m.current_students > 0]),
            "total_capacity": total_capacity,
            "used_capacity": used_capacity,
            "available_capacity": available_capacity,
            "utilization_rate": utilization_rate,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _apply_student_filters(
        self, students: List[Student], filters: Optional[Dict]
    ) -> List[Student]:
        if not filters:
            return students
        result = students
        if "center_id" in filters:
            center_id = filters["center_id"]
            result = [s for s in result if s.center_id == center_id]
        if "grade_level" in filters:
            grade = filters["grade_level"]
            result = [s for s in result if s.grade_level == grade]
        return result

    def _apply_mentor_filters(
        self, mentors: List[Mentor], filters: Optional[Dict]
    ) -> List[Mentor]:
        if not filters:
            return mentors
        result = mentors
        if "center_id" in filters:
            center_id = filters["center_id"]
            result = [m for m in result if m.center_id == center_id]
        if "grade_level" in filters:
            grade = filters["grade_level"]
            result = [m for m in result if grade in m.supported_grades]
        return result

    def _is_assigned(self, student_id: int) -> bool:
        return any(item["student_id"] == student_id for item in self.assignments)

    def _find_mentor(self, mentor_id: int) -> Optional[Mentor]:
        for mentor in self.mentors:
            if mentor.id == mentor_id:
                return mentor
        return None

    def _generate_sample_students(self, count: int) -> List[Student]:
        students: List[Student] = []
        for idx in range(1, count + 1):
            students.append(
                Student(
                    id=idx,
                    name=self._faker.name(),
                    gender=self._faker.random_int(0, 1),
                    grade_level=self._faker.random_element([10, 11, 12]),
                    center_id=self._faker.random_element([1, 2, 3]),
                    registration_status=self._faker.random_int(0, 2),
                    academic_status=1,
                    is_school_student=self._faker.boolean(chance_of_getting_true=30),
                )
            )
        return students

    def _generate_sample_mentors(self, count: int) -> List[Mentor]:
        mentors: List[Mentor] = []
        grade_combinations = [
            [10],
            [11],
            [12],
            [10, 11],
            [11, 12],
            [10, 11, 12],
        ]
        for idx in range(1, count + 1):
            mentors.append(
                Mentor(
                    id=idx,
                    name=f"استاد {self._faker.last_name()}",
                    gender=self._faker.random_int(0, 1),
                    supported_grades=self._faker.random_element(grade_combinations),
                    max_capacity=self._faker.random_int(5, 15),
                    current_students=self._faker.random_int(0, 8),
                    center_id=self._faker.random_element([1, 2, 3]),
                    primary_grade=self._faker.random_element([10, 11, 12]),
                )
            )
        return mentors
