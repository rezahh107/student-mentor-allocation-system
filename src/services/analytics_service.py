from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import jdatetime

from src.api.client import APIClient
from src.api.models import StudentDTO


@dataclass
class DashboardData:
    """کانتینر داده‌های داشبورد."""

    total_students: int
    active_students: int
    pending_allocations: int
    growth_rate: str
    growth_trend: str
    active_percentage: float
    pending_percentage: float
    gender_distribution: Dict[int, int]
    monthly_registrations: List[Dict[str, Any]]
    center_performance: Dict[int, int]
    age_distribution: List[int]
    recent_activities: List[Dict[str, str]]
    performance_metrics: Dict[str, Any]
    last_updated: datetime


class AnalyticsService:
    """سرویس تحلیل داده برای داشبورد."""

    def __init__(self, api_client: APIClient) -> None:
        self.api_client = api_client
        self._cache: Dict[str, DashboardData] = {}
        self._cache_time: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=5)
        self.max_records_threshold = 10_000

    async def load_dashboard_data(
        self,
        date_range: Optional[Tuple[datetime, datetime]] = None,
        *,
        force_refresh: bool = False,
    ) -> DashboardData:
        """بارگذاری داده‌های داشبورد با بهینه‌سازی عملکرد و کش."""

        if not date_range:
            end = datetime.now()
            start = end - timedelta(days=30)
            date_range = (start, end)

        start_date, end_date = date_range
        key = f"{start_date.isoformat()}_{end_date.isoformat()}"
        if not force_refresh and key in self._cache:
            ts = self._cache_time.get(key)
            if ts and datetime.now() - ts < self.cache_ttl:
                return self._cache[key]

        # تصمیم‌گیری بر اساس حجم داده‌ها در سرور (در Mock تقریبی)
        total_students_count = 0
        try:
            stats = await self.api_client.get_dashboard_stats()
            # DashboardStatsDTO
            total_students_count = getattr(stats, "total_students", 0)
        except Exception:
            total_students_count = 0

        if total_students_count and total_students_count > self.max_records_threshold:
            data = await self._load_with_backend_filtering(date_range)
        else:
            data = await self._load_with_client_filtering(date_range)

        self._cache[key] = data
        self._cache_time[key] = datetime.now()
        return data

    async def _load_with_client_filtering(self, date_range: Tuple[datetime, datetime]) -> DashboardData:
        start_date, end_date = date_range
        students = await self.api_client.get_students()
        in_range = [s for s in students if s.created_at and (start_date <= s.created_at <= end_date)]
        return await self._process(students_all=students, current=in_range, date_range=date_range)

    async def _load_with_backend_filtering(self, date_range: Tuple[datetime, datetime]) -> DashboardData:
        start_date, end_date = date_range
        # تلاش برای فیلتر سمت سرور؛ در Mock ممکن است نادیده گرفته شود.
        filters = {
            "created_at__gte": start_date.isoformat(),
            "created_at__lte": end_date.isoformat(),
        }
        try:
            resp = await self.api_client.get_students(filters)
            current = list(resp)
        except Exception:
            # بازگشت به سمت کلاینت در صورت عدم پشتیبانی سرور
            students = await self.api_client.get_students()
            current = [s for s in students if s.created_at and (start_date <= s.created_at <= end_date)]

        # برای برخی شاخص‌ها به کل دیتا نیز نیاز است
        try:
            students_all = await self.api_client.get_students()
        except Exception:
            students_all = list(current)

        return await self._process(students_all=students_all, current=current, date_range=date_range)

    async def _process(
        self,
        *,
        students_all: List[StudentDTO],
        current: List[StudentDTO],
        date_range: Tuple[datetime, datetime],
    ) -> DashboardData:
        total_students = len(current)
        active_students = sum(1 for s in current if s.education_status == 1)
        pending_allocations = sum(1 for s in current if not s.allocation_status)

        growth = self._growth_rate(students_all, date_range)
        gender_distribution = self._gender_dist(current)
        monthly = self._monthly_trend(current)
        center_perf = self._center_perf(current)
        ages = self._age_dist(current)
        activities = self._recent_activities(current)
        performance = self._performance_metrics(current)

        return DashboardData(
            total_students=total_students,
            active_students=active_students,
            pending_allocations=pending_allocations,
            growth_rate=growth["rate"],
            growth_trend=growth["trend"],
            active_percentage=(active_students / total_students * 100) if total_students else 0.0,
            pending_percentage=(pending_allocations / total_students * 100) if total_students else 0.0,
            gender_distribution=gender_distribution,
            monthly_registrations=monthly,
            center_performance=center_perf,
            age_distribution=ages,
            recent_activities=activities,
            performance_metrics=performance,
            last_updated=datetime.now(),
        )

    def _growth_rate(self, students_all: List[StudentDTO], date_range: Tuple[datetime, datetime]) -> Dict[str, str]:
        start, end = date_range
        dur = end - start
        prev_start = start - dur
        prev_end = start
        cur_count = sum(1 for s in students_all if s.created_at and start <= s.created_at <= end)
        prev_count = sum(1 for s in students_all if s.created_at and prev_start <= s.created_at <= prev_end)
        if prev_count == 0:
            return {"rate": "+100%", "trend": "up"}
        rate = ((cur_count - prev_count) / prev_count) * 100
        trend = "up" if rate > 0 else ("down" if rate < 0 else "stable")
        sign = "+" if rate > 0 else ""
        return {"rate": f"{sign}{rate:.1f}%", "trend": trend}

    def _gender_dist(self, students: List[StudentDTO]) -> Dict[int, int]:
        out = {0: 0, 1: 0}
        for s in students:
            if s.gender in out:
                out[s.gender] += 1
        return out

    def _monthly_trend(self, students: List[StudentDTO]) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        for s in students:
            if not s.created_at:
                continue
            month = jdatetime.date.fromgregorian(date=s.created_at.date()).strftime("%Y/%m")
            counts[month] = counts.get(month, 0) + 1
        return [
            {"month": m, "count": counts[m], "month_name": jdatetime.datetime.strptime(m, "%Y/%m").strftime("%B %Y")}
            for m in sorted(counts.keys())
        ]

    def _center_perf(self, students: List[StudentDTO]) -> Dict[int, int]:
        c: Dict[int, int] = {}
        for s in students:
            c[s.center] = c.get(s.center, 0) + 1
        return c

    @staticmethod
    def get_center_name(center_id: int) -> str:
        names = {1: "مرکز اصلی", 2: "گلستان", 3: "صدرا", 4: "شعبه جدید"}
        return names.get(center_id, f"مرکز {center_id}")

    def _age_dist(self, students: List[StudentDTO]) -> List[int]:
        out: List[int] = []
        today = datetime.now().date()
        for s in students:
            if s.birth_date:
                age = (today - s.birth_date).days // 365
                if 10 < age < 40:
                    out.append(age)
        return out

    def _recent_activities(self, students: List[StudentDTO]) -> List[Dict[str, str]]:
        recent = sorted([s for s in students if s.created_at], key=lambda x: x.created_at, reverse=True)[:10]
        center_names = {1: "مرکز", 2: "گلستان", 3: "صدرا"}
        items: List[Dict[str, str]] = []
        for s in recent:
            dt = jdatetime.datetime.fromgregorian(datetime=s.created_at)
            items.append(
                {
                    "time": dt.strftime("%H:%M"),
                    "type": "registration",
                    "icon": "🟢",
                    "message": f"ثبت‌نام جدید: {s.first_name} {s.last_name} ({center_names.get(s.center, s.center)})",
                    "details": f"کد: {s.counter}",
                }
            )
        return items

    def _performance_metrics(self, students: List[StudentDTO]) -> Dict[str, Any]:
        center_capacities = {1: 500, 2: 400, 3: 300}
        perf: Dict[str, Any] = {"center_utilization": {}, "registration_types": {}, "school_types": {}}
        center_counts = self._center_perf(students)
        for cid, cap in center_capacities.items():
            reg = center_counts.get(cid, 0)
            util = (reg / cap * 100) if cap else 0
            perf["center_utilization"][cid] = {
                "registered": reg,
                "capacity": cap,
                "utilization": util,
                "available": cap - reg,
            }
        for s in students:
            perf["registration_types"][s.registration_status] = perf["registration_types"].get(s.registration_status, 0) + 1
            st = s.school_type or "normal"
            perf["school_types"][st] = perf["school_types"].get(st, 0) + 1
        perf["total_capacity"] = sum(center_capacities.values())
        perf["total_registered"] = len(students)
        perf["overall_utilization"] = (len(students) / perf["total_capacity"] * 100) if perf["total_capacity"] else 0
        return perf
