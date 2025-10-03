"""Mock service for mentor management to support UI development."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import copy

from src.core.clock import SupportsNow, tehran_clock


class MockMentorService:
    """In-memory mentor service used during UI prototyping."""

    def __init__(self, *, clock: SupportsNow | None = None) -> None:
        self._clock = clock or tehran_clock()
        self._mentors: List[Dict[str, Any]] = [
            {
                "id": 1,
                "name": "علی احمدی",
                "gender": 1,
                "is_school": False,
                "capacity": 15,
                "current_load": 8,
                "remaining_capacity": 7,
                "is_active": True,
                "phone": "09123456789",
                "created_at": self._clock.now(),
                "groups": ["کنکوری", "متوسطه دوم"],
            },
            {
                "id": 2,
                "name": "فاطمه رضایی",
                "gender": 0,
                "is_school": True,
                "capacity": 12,
                "current_load": 5,
                "remaining_capacity": 7,
                "is_active": True,
                "phone": "09987654321",
                "created_at": self._clock.now(),
                "groups": ["متوسطه اول", "دبستان"],
            },
            {
                "id": 3,
                "name": "محمد کریمی",
                "gender": 1,
                "is_school": False,
                "capacity": 20,
                "current_load": 18,
                "remaining_capacity": 2,
                "is_active": True,
                "phone": "09111222333",
                "created_at": self._clock.now(),
                "groups": ["کنکوری", "هنرستان"],
            },
            {
                "id": 4,
                "name": "زهرا موسوی",
                "gender": 0,
                "is_school": True,
                "capacity": 10,
                "current_load": 10,
                "remaining_capacity": 0,
                "is_active": False,
                "phone": "09444555666",
                "created_at": self._clock.now(),
                "groups": ["متوسطه اول"],
            },
        ]
        self._next_id = 5

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------
    def get_all_mentors(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        mentors = copy.deepcopy(self._mentors)
        if not filters:
            return mentors

        if "gender" in filters:
            mentors = [m for m in mentors if m["gender"] == filters["gender"]]
        if "is_school" in filters:
            mentors = [m for m in mentors if m["is_school"] == filters["is_school"]]
        if "is_active" in filters:
            mentors = [m for m in mentors if m["is_active"] == filters["is_active"]]
        if "min_capacity" in filters:
            mentors = [m for m in mentors if m["remaining_capacity"] >= filters["min_capacity"]]
        return mentors

    def get_mentor_by_id(self, mentor_id: int) -> Optional[Dict[str, Any]]:
        for mentor in self._mentors:
            if mentor["id"] == mentor_id:
                return copy.deepcopy(mentor)
        return None

    def create_mentor(self, mentor_data: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_new_mentor(mentor_data)
        new_mentor = {
            "id": self._next_id,
            "name": mentor_data["name"].strip(),
            "gender": mentor_data["gender"],
            "is_school": mentor_data["is_school"],
            "capacity": mentor_data["capacity"],
            "current_load": 0,
            "remaining_capacity": mentor_data["capacity"],
            "is_active": mentor_data.get("is_active", True),
            "phone": mentor_data.get("phone", ""),
            "created_at": self._clock.now(),
            "groups": mentor_data.get("groups", []),
            "notes": mentor_data.get("notes", ""),
        }
        self._mentors.append(new_mentor)
        self._next_id += 1
        return copy.deepcopy(new_mentor)

    def update_mentor(self, mentor_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
        mentor = self.get_mentor_by_id(mentor_id)
        if not mentor:
            raise ValueError(f"پشتیبان با شناسه {mentor_id} یافت نشد")
        self._validate_updates(updates)

        for i, record in enumerate(self._mentors):
            if record["id"] == mentor_id:
                record.update(updates)
                if "capacity" in updates:
                    capacity = updates["capacity"]
                    current_load = record.get("current_load", 0)
                    record["remaining_capacity"] = max(capacity - current_load, 0)
                return copy.deepcopy(record)
        raise ValueError(f"خطا در بروزرسانی پشتیبان {mentor_id}")

    def delete_mentor(self, mentor_id: int) -> bool:
        mentor = self.get_mentor_by_id(mentor_id)
        if not mentor:
            raise ValueError(f"پشتیبان با شناسه {mentor_id} یافت نشد")
        if mentor["current_load"] > 0:
            raise ValueError("نمی‌توان پشتیبان با بار کاری فعال را حذف کرد")
        self._mentors = [m for m in self._mentors if m["id"] != mentor_id]
        return True

    def get_mentor_stats(self) -> Dict[str, Any]:
        total = len(self._mentors)
        active = len([m for m in self._mentors if m["is_active"]])
        male = len([m for m in self._mentors if m["gender"] == 1])
        female = total - male
        school = len([m for m in self._mentors if m["is_school"]])
        regular = total - school
        total_capacity = sum(m["capacity"] for m in self._mentors)
        total_load = sum(m["current_load"] for m in self._mentors)
        utilization = (total_load / total_capacity * 100) if total_capacity else 0
        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "male": male,
            "female": female,
            "school": school,
            "regular": regular,
            "total_capacity": total_capacity,
            "total_load": total_load,
            "utilization_rate": utilization,
        }

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_new_mentor(mentor_data: Dict[str, Any]) -> None:
        required_fields = ["name", "gender", "is_school", "capacity"]
        for field in required_fields:
            if field not in mentor_data:
                raise ValueError(f"فیلد {field} الزامی است")

        name = mentor_data["name"].strip()
        if not name:
            raise ValueError("نام پشتیبان نمی‌تواند خالی باشد")

        capacity = mentor_data["capacity"]
        if capacity <= 0:
            raise ValueError("ظرفیت باید مقدار مثبت داشته باشد")

    @staticmethod
    def _validate_updates(updates: Dict[str, Any]) -> None:
        if "name" in updates and not updates["name"].strip():
            raise ValueError("نام پشتیبان نمی‌تواند خالی باشد")
        if "capacity" in updates and updates["capacity"] <= 0:
            raise ValueError("ظرفیت باید مقدار مثبت داشته باشد")
