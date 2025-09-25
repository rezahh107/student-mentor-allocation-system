"""Allocation engine orchestrating policy evaluation and ranking."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .contracts import AllocationConfig, MentorLike, NormalizedMentor, NormalizedStudent, StudentLike
from .policy import EligibilityPolicy, NormalizationError, prepare_mentor, prepare_student
from src.observe.perf import PerformanceObserver


@dataclass
class AllocationTraceEntry:
    """Trace entry for a mentor evaluation."""

    mentor: MentorLike | None
    normalized: NormalizedMentor | None
    passed: bool
    trace: Sequence[dict[str, object]]
    ranking_key: tuple[float, int, int] | None


class AllocationEngine:
    """Execute policy checks and select the best mentor."""

    def __init__(
        self,
        *,
        policy: EligibilityPolicy,
        config: AllocationConfig | None = None,
        observer: PerformanceObserver | None = None,
    ) -> None:
        self.policy = policy
        self.config = config or AllocationConfig()
        self.observer = observer

    def evaluate(
        self, student: StudentLike, mentors: Iterable[MentorLike]
    ) -> tuple[MentorLike | None, List[AllocationTraceEntry]]:
        observer = self.observer
        context = observer.measure("allocation_engine.evaluate") if observer else nullcontext()
        with context:
            try:
                normalized_student = prepare_student(self.policy, student)
            except NormalizationError as error:
                trace_entry = AllocationTraceEntry(
                    mentor=None,
                    normalized=None,
                    passed=False,
                    trace=[
                        {
                            "code": error.rule_code,
                            "passed": False,
                            "details": {"message": str(error), **error.details},
                        }
                    ],
                    ranking_key=None,
                )
                if observer:
                    observer.increment_counter("allocation_no_candidate_total")
                return None, [trace_entry]

            evaluations: List[AllocationTraceEntry] = []
            passed_candidates: List[tuple[tuple[float, int, int], AllocationTraceEntry]] = []
            for mentor in mentors:
                mentor_context = (
                    observer.measure("allocation_engine.evaluate_mentor")
                    if observer
                    else nullcontext()
                )
                with mentor_context:
                    try:
                        normalized_mentor = prepare_mentor(self.policy, mentor)
                    except NormalizationError as error:
                        trace = [
                            {
                                "code": error.rule_code,
                                "passed": False,
                                "details": {"message": str(error), **error.details},
                            }
                        ]
                        entry = AllocationTraceEntry(
                            mentor=mentor,
                            normalized=None,
                            passed=False,
                            trace=trace,
                            ranking_key=None,
                        )
                        evaluations.append(entry)
                        if observer:
                            observer.increment_counter("allocation_policy_failure_total{stage=\"normalization\"}")
                        continue
                    passed, trace = self.policy.evaluate(normalized_student, normalized_mentor)
                    ranking_key = None
                    if observer:
                        for item in trace:
                            metric_name = f'allocation_policy_pass_total{{rule="{item["code"]}"}}'
                            if item["passed"]:
                                observer.increment_counter(metric_name)
                    if passed:
                        occupancy_ratio = self._compute_occupancy_ratio(normalized_mentor)
                        ranking_key = (
                            occupancy_ratio,
                            normalized_mentor.current_load,
                            normalized_mentor.mentor_id,
                        )
                        entry = AllocationTraceEntry(
                            mentor=mentor,
                            normalized=normalized_mentor,
                            passed=passed,
                            trace=trace,
                            ranking_key=ranking_key,
                        )
                        passed_candidates.append((ranking_key, entry))
                    else:
                        entry = AllocationTraceEntry(
                            mentor=mentor,
                            normalized=normalized_mentor,
                            passed=passed,
                            trace=trace,
                            ranking_key=None,
                        )
                    evaluations.append(entry)
            best_entry = None
            if passed_candidates:
                passed_candidates.sort(key=lambda item: item[0])
                best_entry = passed_candidates[0][1]
            if best_entry is None and observer:
                observer.increment_counter("allocation_no_candidate_total")
            return (best_entry.mentor if best_entry else None, evaluations)

    @staticmethod
    def _compute_occupancy_ratio(mentor: NormalizedMentor) -> float:
        if mentor.capacity <= 0:
            return 1.0
        return mentor.current_load / mentor.capacity

