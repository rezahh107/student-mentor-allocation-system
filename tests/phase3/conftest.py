"""Common fixtures and helpers for phase 3 allocation tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping

import pytest

from sma.phase3_allocation.contracts import (
    AllocationConfig,
    NormalizedMentor,
    NormalizedStudent,
)
from sma.phase3_allocation.policy import EligibilityPolicy
from sma.phase3_allocation.providers import ManagerCentersProvider, SpecialSchoolsProvider


@dataclass
class DummyStudent:
    gender: int
    group_code: str
    reg_center: int
    reg_status: int
    edu_status: int = 1
    school_code: int | None = None
    student_type: int = 0
    roster_year: int | None = None


@dataclass
class DummyMentor:
    mentor_id: int | str
    gender: int
    allowed_groups: Iterable[str]
    allowed_centers: Iterable[int]
    capacity: int
    current_load: int
    is_active: bool
    mentor_type: str
    special_schools: Iterable[int] = field(default_factory=list)
    manager_id: int | None = None


class DictManagerCentersProvider(ManagerCentersProvider):
    def __init__(self, mapping: Mapping[int, FrozenSet[int]]):
        self._mapping = dict(mapping)

    def get_allowed_centers(self, manager_id: int) -> FrozenSet[int] | None:
        return self._mapping.get(manager_id)


class DictSpecialSchoolsProvider(SpecialSchoolsProvider):
    def __init__(self, mapping: Mapping[int, FrozenSet[int]]):
        self._mapping = dict(mapping)

    def get(self, year: int) -> FrozenSet[int] | None:
        return self._mapping.get(year)


@pytest.fixture
def special_provider() -> DictSpecialSchoolsProvider:
    return DictSpecialSchoolsProvider({1402: frozenset({101, 202}), 1403: frozenset({303})})


@pytest.fixture
def manager_provider() -> DictManagerCentersProvider:
    return DictManagerCentersProvider({10: frozenset({0, 1}), 11: frozenset({2})})


@pytest.fixture
def policy(special_provider: DictSpecialSchoolsProvider, manager_provider: DictManagerCentersProvider) -> EligibilityPolicy:
    return EligibilityPolicy(special_provider, manager_provider, AllocationConfig())


def normalized_student(**overrides: object) -> NormalizedStudent:
    base = dict(
        gender=0,
        group_code="A",
        reg_center=0,
        reg_status=0,
        edu_status=1,
        school_code=None,
        student_type=0,
        roster_year=None,
        warnings=frozenset(),
    )
    base.update(overrides)
    return NormalizedStudent(**base)


def normalized_mentor(**overrides: object) -> NormalizedMentor:
    base = dict(
        mentor_id=1,
        gender=0,
        allowed_groups=frozenset({"A"}),
        allowed_centers=frozenset({0}),
        capacity=5,
        current_load=2,
        is_active=True,
        mentor_type="NORMAL",
        special_schools=frozenset({101, 202}),
        manager_id=None,
    )
    base.update(overrides)
    return NormalizedMentor(**base)

