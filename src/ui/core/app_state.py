from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal, Optional

from src.api.models import AllocationDTO, DashboardStatsDTO, MentorDTO, StudentDTO


@dataclass
class AppState:
    """State مرکزی برنامه.

    ویژگی‌ها:
        api_mode: حالت API (mock/real).
        current_page: صفحه فعال در UI.
        is_loading: وضعیت بارگذاری کلی.
        students: لیست دانش‌آموزان.
        mentors: لیست منتورها.
        allocations: لیست تخصیص‌ها.
        stats: آمار داشبورد.
        last_update: زمان آخرین بروزرسانی داده‌ها.
        error_message: پیام خطای آخر.
    """

    api_mode: Literal["mock", "real"] = "mock"
    current_page: str = "dashboard"
    is_loading: bool = False
    students: List[StudentDTO] = field(default_factory=list)
    mentors: List[MentorDTO] = field(default_factory=list)
    allocations: List[AllocationDTO] = field(default_factory=list)
    stats: Optional[DashboardStatsDTO] = None
    last_update: Optional[datetime] = None
    error_message: Optional[str] = None

