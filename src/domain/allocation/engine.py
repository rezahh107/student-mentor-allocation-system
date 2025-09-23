# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from src.domain.allocation.rules import (
    AllowedCenterRule,
    AllowedGroupRule,
    CapacityRule,
    GenderRule,
    GraduateConstraintRule,
    SchoolTypeRule,
    Rule,
)
from src.domain.mentor.entities import Mentor
from src.domain.shared.types import RuleResult
from src.domain.student.entities import Student


@dataclass(slots=True)
class SelectionResult:
    mentor_id: int | None
    reason: str | None
    rule_trace: list[str]


class AllocationEngine:
    """Applies six-factor AND rules and ranks by occupancy and load."""

    def __init__(self, rules: Sequence[Rule] | None = None) -> None:
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

    def select_best(self, student: Student, candidates: Iterable[Mentor]) -> SelectionResult:
        passing: list[Tuple[Mentor, list[str]]] = []
        for m in candidates:
            trace: list[str] = []
            failed = False
            for rule in self.rules:
                r: RuleResult = rule.check(student, m)
                trace.append(r.reason or "OK")
                if not r.ok:
                    failed = True
                    break
            if not failed:
                passing.append((m, trace))

        if not passing:
            return SelectionResult(None, "NoEligibleMentor", ["-" for _ in self.rules])

        # Rank by occupancy ratio asc, then current_load asc, then mentor_id asc for stability
        passing.sort(key=lambda t: (t[0].occupancy_ratio, t[0].current_load, t[0].mentor_id))
        best, trace = passing[0]
        return SelectionResult(best.mentor_id, None, trace)

