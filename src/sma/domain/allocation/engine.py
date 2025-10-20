# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from sma.domain.allocation.fairness import FairnessConfig, FairnessPlanner, FairnessStrategy
from sma.domain.allocation.reasons import (
    LocalizedReason,
    ReasonCode,
    RuleResult,
    build_reason,
)
from sma.domain.allocation.rules import (
    AllowedCenterRule,
    AllowedGroupRule,
    CapacityRule,
    GenderRule,
    GraduateConstraintRule,
    SchoolTypeRule,
    Rule,
)
from sma.domain.mentor.entities import Mentor
from sma.domain.student.entities import Student


@dataclass(slots=True)
class SelectionResult:
    mentor_id: int | None
    reason: LocalizedReason | None
    rule_trace: list[LocalizedReason | None]
    fairness_strategy: FairnessStrategy
    fairness_key: str


class AllocationEngine:
    """Applies six-factor AND rules and ranks by occupancy and load."""

    def __init__(
        self,
        rules: Sequence[Rule] | None = None,
        *,
        fairness: FairnessConfig | None = None,
    ) -> None:
        self.rules: Sequence[Rule] = (
            rules
            or (
                GenderRule(),
                AllowedGroupRule(),
                AllowedCenterRule(),
                CapacityRule(),
                GraduateConstraintRule(),
                SchoolTypeRule(),
            )
        )
        self._fairness_config = fairness or FairnessConfig()
        self._fairness = FairnessPlanner(self._fairness_config)

    def select_best(
        self,
        student: Student,
        candidates: Iterable[Mentor],
        *,
        academic_year: str | None = None,
    ) -> SelectionResult:
        passing: list[Tuple[Mentor, list[LocalizedReason | None]]] = []
        last_failure_trace: list[LocalizedReason | None] | None = None
        for m in candidates:
            trace: list[LocalizedReason | None] = []
            failed = False
            for rule in self.rules:
                r: RuleResult = rule.check(student, m)
                trace.append(r.reason)
                if not r.ok:
                    failed = True
                    break
            if not failed:
                passing.append((m, trace))
            else:
                last_failure_trace = trace

        fairness_key = self._resolve_fairness_key(student, academic_year)

        if not passing:
            reason = build_reason(ReasonCode.NO_ELIGIBLE_MENTOR)
            trace = last_failure_trace or []
            if len(trace) < len(self.rules):
                trace = trace + [None] * (len(self.rules) - len(trace))
            normalized_trace = [entry or reason for entry in trace[: len(self.rules)]]
            return SelectionResult(None, reason, normalized_trace, self._fairness_config.strategy, fairness_key)

        base_sorted = sorted(
            passing,
            key=lambda t: (
                t[0].occupancy_ratio,
                t[0].current_load,
                t[0].mentor_id,
            ),
        )
        ranked = self._fairness.rank(base_sorted, academic_year=fairness_key)
        best, trace = ranked[0]
        return SelectionResult(best.mentor_id, None, trace, self._fairness_config.strategy, fairness_key)

    @staticmethod
    def _resolve_fairness_key(student: Student, academic_year: str | None) -> str:
        if academic_year:
            return academic_year
        counter = getattr(student, "counter", None) or ""
        if isinstance(counter, str) and len(counter) >= 2 and counter[:2].isdigit():
            return counter[:2]
        fallback = getattr(student, "academic_year", None)
        if isinstance(fallback, str) and fallback:
            return fallback
        return "default"

