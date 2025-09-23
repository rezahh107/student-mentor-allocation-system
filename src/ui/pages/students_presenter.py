from __future__ import annotations

import asyncio
from typing import Dict, List, Tuple

from src.api.client import APIClient
from src.api.models import StudentDTO
from src.ui.core.event_bus import EventBus


class StudentsPresenter:
    """Presenter صفحه دانش‌آموزان با مدیریت فیلتر، جستجو، صفحه‌بندی و CRUD."""

    def __init__(self, api_client: APIClient, event_bus: EventBus) -> None:
        self.api_client = api_client
        self.event_bus = event_bus

        self.students: List[StudentDTO] = []
        self.total_count: int = 0
        self.current_filters: Dict = {}
        self.search_term: str = ""

    async def load_students(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Dict | None = None,
        search: str = "",
    ) -> Tuple[List[StudentDTO], int]:
        """لود دانش‌آموزان با صفحه‌بندی و فیلترها. خروجی: (لیست، تعداد کل)."""
        await self.event_bus.emit("loading_start", "در حال دریافت لیست دانش‌آموزان...")
        try:
            api_filters = dict(filters or {})
            api_filters["page"] = page
            api_filters["page_size"] = page_size

            if hasattr(self.api_client, "get_students_paginated"):
                result = await self.api_client.get_students_paginated(api_filters)
                students = result.get("students", [])
                total_count = int(result.get("total_count", len(students)))
            else:
                all_students = await self.api_client.get_students(api_filters)
                total_count = len(all_students)
                start = (page - 1) * page_size
                end = start + page_size
                students = all_students[start:end]

            self.students = students
            self.total_count = total_count
            self.current_filters = filters or {}
            self.search_term = search

            await self.event_bus.emit(
                "students_loaded",
                {
                    "students": students,
                    "total_count": total_count,
                    "page": page,
                    "page_size": page_size,
                },
            )
            return students, total_count
        except Exception as e:  # noqa: BLE001
            await self.event_bus.emit("error", f"خطا در دریافت لیست دانش‌آموزان: {e}")
            return [], 0
        finally:
            await self.event_bus.emit("loading_end")

    async def add_student(self, student_data: Dict) -> bool:
        await self.event_bus.emit("loading_start", "در حال افزودن دانش‌آموز...")
        try:
            if not (student_data.get("first_name") and student_data.get("last_name")):
                raise ValueError("نام و نام خانوادگی الزامی است")
            await self.api_client.create_student(student_data)
            await self.event_bus.emit("success", "دانش‌آموز با موفقیت اضافه شد")
            return True
        except Exception as e:  # noqa: BLE001
            await self.event_bus.emit("error", f"خطا در افزودن دانش‌آموز: {e}")
            return False
        finally:
            await self.event_bus.emit("loading_end")

    async def update_student(self, student_id: int, student_data: Dict) -> bool:
        await self.event_bus.emit("loading_start", "در حال بروزرسانی دانش‌آموز...")
        try:
            await self.api_client.update_student(student_id, student_data)
            await self.event_bus.emit("success", "اطلاعات دانش‌آموز بروزرسانی شد")
            return True
        except Exception as e:  # noqa: BLE001
            await self.event_bus.emit("error", f"خطا در بروزرسانی: {e}")
            return False
        finally:
            await self.event_bus.emit("loading_end")

    async def delete_student(self, student_id: int) -> bool:
        await self.event_bus.emit("loading_start", "در حال حذف دانش‌آموز...")
        try:
            await self.api_client.delete_student(student_id)
            await self.event_bus.emit("success", "دانش‌آموز حذف شد")
            return True
        except Exception as e:  # noqa: BLE001
            await self.event_bus.emit("error", f"خطا در حذف: {e}")
            return False
        finally:
            await self.event_bus.emit("loading_end")
