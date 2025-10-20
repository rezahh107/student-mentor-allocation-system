from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Dict, List, Optional, TYPE_CHECKING

from sma.ui.qt_optional import QtCore, require_qt

require_qt()

QObject = QtCore.QObject
Signal = QtCore.Signal

from ...core.allocation_engine import AllocationEngine
from ...core.models import Mentor, Student
from ..services.allocation_backend import IBackendService, MockBackendService
from ..services.excel_exporter import ExcelExporter

if TYPE_CHECKING:
    from ..services.performance_monitor import PerformanceMonitor


class AllocationPresenter(QObject):
    """Coordinates between backend services, engine, and the UI layer."""

    statistics_ready = Signal(dict)
    allocation_completed = Signal(dict)
    backend_error = Signal(str)

    def __init__(
        self,
        backend_service: Optional[IBackendService] = None,
        engine: Optional[AllocationEngine] = None,
        exporter: Optional[ExcelExporter] = None,
    ) -> None:
        super().__init__()
        self.backend = backend_service or MockBackendService()
        self.engine = engine or AllocationEngine()
        self.exporter = exporter or ExcelExporter()
        self._last_students: List[Student] = []
        self._last_mentors: List[Mentor] = []
        self.performance_monitor: Optional["PerformanceMonitor"] = None

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    async def load_statistics(self) -> Dict[str, int]:
        try:
            base_stats = await self.backend.get_allocation_statistics()
            summary = self._normalise_statistics(base_stats)
            self.statistics_ready.emit(summary)
            return summary
        except Exception as exc:  # noqa: BLE001
            self.backend_error.emit(str(exc))
            raise

    async def fetch_students(self, filters: Optional[Dict] = None) -> List[Student]:
        return await self.backend.get_unassigned_students(filters)

    async def fetch_mentors(self, filters: Optional[Dict] = None) -> List[Mentor]:
        return await self.backend.get_available_mentors(filters)

    # ------------------------------------------------------------------
    # Allocation flow
    # ------------------------------------------------------------------
    async def allocate_students(
        self,
        *,
        same_center_only: bool,
        prefer_lower_load: bool,
        filters: Optional[Dict] = None,
        capacity_weight: Optional[int] = None,
    ) -> Dict[str, object]:
        try:
            students = await self.fetch_students(filters)
            mentors = await self.fetch_mentors(filters)
        except Exception as exc:  # noqa: BLE001
            self.backend_error.emit(str(exc))
            raise

        self._last_students = students
        self._last_mentors = mentors

        payload: Dict[str, object] = {
            "students": students,
            "mentors": mentors,
            "results": {
                "successful": 0,
                "failed": 0,
                "assignments": [],
                "errors": [],
            },
        }

        if not students or not mentors:
            return payload

        self.engine.reset()
        self.engine.rules.require_same_center = same_center_only
        if capacity_weight is not None:
            self.engine.rules.capacity_weight = capacity_weight
        else:
            self.engine.rules.capacity_weight = 10 if prefer_lower_load else 0

        mentor_pool = [replace(m) for m in mentors]
        results = self.engine.allocate_students(students, mentor_pool)
        payload["results"] = results
        payload["stats"] = self._summarise_after_allocation(students, mentor_pool)
        self.allocation_completed.emit(results)
        return payload

    async def run_allocation(
        self,
        *,
        same_center_only: bool = True,
        prefer_lower_load: bool = True,
        filters: Optional[Dict] = None,
        capacity_weight: Optional[int] = None,
    ) -> Dict[str, object]:
        """Convenience helper that persists and returns allocation results only."""

        payload = await self.allocate_students(
            same_center_only=same_center_only,
            prefer_lower_load=prefer_lower_load,
            filters=filters,
            capacity_weight=capacity_weight,
        )
        results: Dict[str, object] = payload.get("results", {})
        if results.get("assignments"):
            await self.persist_results(results)
        return results

    async def persist_results(self, results: Dict[str, object]) -> None:
        if not results.get("assignments"):
            return
        await self.backend.save_allocation_results(results)

    # ------------------------------------------------------------------
    # Export & analytics
    # ------------------------------------------------------------------
    async def export_results(self, results: Dict, file_path: str) -> bool:
        if not results or not results.get("assignments"):
            return False

        students = self._last_students or await self.backend.get_unassigned_students()
        mentors = self._last_mentors or await self.backend.get_available_mentors()
        return await self.exporter.export_allocation_results(results, students, mentors, file_path)

    async def get_detailed_statistics(self) -> Dict:
        base = await self.backend.get_allocation_statistics()
        students = await self.backend.get_unassigned_students()
        mentors = await self.backend.get_available_mentors()

        grade_distribution: Dict[int, int] = {}
        gender_distribution = {"male": 0, "female": 0}
        center_distribution: Dict[int, int] = {}

        for student in students:
            grade_distribution[student.grade_level] = grade_distribution.get(student.grade_level, 0) + 1
            if student.gender == 1:
                gender_distribution["male"] += 1
            else:
                gender_distribution["female"] += 1
            center_distribution[student.center_id] = center_distribution.get(student.center_id, 0) + 1

        base.update(
            {
                "grade_distribution": grade_distribution,
                "gender_distribution": gender_distribution,
                "center_distribution": center_distribution,
                "mentor_capacity_analysis": self._analyze_mentor_capacity(mentors),
            }
        )
        return base

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _normalise_statistics(self, stats: Dict) -> Dict[str, int]:
        total_capacity = stats.get("total_capacity", 0)
        available_capacity = stats.get("available_capacity")
        if available_capacity is None and total_capacity:
            available_capacity = total_capacity - stats.get("used_capacity", 0)

        return {
            "students": stats.get("total_students", stats.get("students", 0)),
            "mentors": stats.get("total_mentors", stats.get("mentors", 0)),
            "total_capacity": total_capacity,
            "available_capacity": available_capacity or 0,
        }

    def _summarise_after_allocation(self, students: List[Student], mentors: List[Mentor]) -> Dict[str, int]:
        return {
            "students": len(students),
            "mentors": len(mentors),
            "total_capacity": sum(m.max_capacity for m in mentors),
            "available_capacity": sum(max(0, m.remaining_capacity()) for m in mentors),
        }

    def _analyze_mentor_capacity(self, mentors: List[Mentor]) -> Dict:
        total = len(mentors)
        if total == 0:
            return {"total": 0, "overloaded": 0, "optimal": 0, "underutilized": 0, "average_utilization": 0}

        overloaded = len([m for m in mentors if m.current_students >= m.max_capacity])
        underutilized = len([m for m in mentors if m.current_students < m.max_capacity * 0.5])
        optimal = total - overloaded - underutilized
        ratios = [
            m.current_students / m.max_capacity
            for m in mentors
            if m.max_capacity > 0
        ]
        average_utilization = sum(ratios) / len(ratios) * 100 if ratios else 0

        return {
            "total": total,
            "overloaded": overloaded,
            "optimal": optimal,
            "underutilized": underutilized,
            "average_utilization": round(average_utilization, 1),
        }

    async def _call_backend(self, method_name: str, *args, **kwargs):  # pragma: no cover - compatibility
        method = getattr(self.backend, method_name, None)
        if not method:
            return None
        outcome = method(*args, **kwargs)
        if inspect.isawaitable(outcome):
            return await outcome
        return outcome
