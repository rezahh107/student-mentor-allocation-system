"""Core contracts and literals for phase 3 allocation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Literal, Protocol, TypedDict, runtime_checkable

Gender = Literal[0, 1]
RegistrationCenter = Literal[0, 1, 2]
RegistrationStatus = Literal[0, 1, 3]
MentorType = Literal["NORMAL", "SCHOOL"]
StudentType = Literal[0, 1]
RuleCode = Literal[
    "GENDER_MATCH",
    "GROUP_ALLOWED",
    "CENTER_ALLOWED",
    "REG_STATUS_ALLOWED",
    "CAPACITY_AVAILABLE",
    "SCHOOL_TYPE_COMPATIBLE",
    "GRADUATE_NOT_TO_SCHOOL",
    "MANAGER_CENTER_GATE",
]


class TraceEntry(TypedDict):
    """Trace entry schema for rule evaluations."""

    code: RuleCode
    passed: bool
    details: Dict[str, object]


@runtime_checkable
class StudentLike(Protocol):
    """Typed protocol describing required student attributes."""

    gender: Gender | int | str | None
    group_code: str | int | None
    reg_center: RegistrationCenter | int | str | None
    reg_status: RegistrationStatus | int | str | None
    edu_status: int | str | None
    school_code: int | str | None
    student_type: StudentType | int | str | None
    roster_year: int | None


@runtime_checkable
class MentorLike(Protocol):
    """Typed protocol describing required mentor attributes."""

    mentor_id: int | str
    gender: Gender | int | str | None
    allowed_groups: Iterable[str | int]
    allowed_centers: Iterable[int | str]
    reg_center: RegistrationCenter | int | str | None
    reg_status: RegistrationStatus | int | str | None
    capacity: int | str
    current_load: int | str
    is_active: bool
    mentor_type: MentorType | str
    special_schools: Iterable[int | str]
    manager_id: int | str | None


@dataclass(frozen=True)
class AllocationConfig:
    """Configuration for allocation evaluation."""

    fast_fail: bool = False
    trace_limit_rejected: int | None = None


@dataclass(frozen=True)
class NormalizedStudent:
    """Normalized student structure used by rules."""

    gender: Gender
    group_code: str
    reg_center: RegistrationCenter
    reg_status: RegistrationStatus
    edu_status: int
    school_code: int | None
    student_type: StudentType
    roster_year: int | None
    warnings: FrozenSet[str]


@dataclass(frozen=True)
class NormalizedMentor:
    """Normalized mentor structure used by rules and ranking."""

    mentor_id: int
    gender: Gender
    allowed_groups: FrozenSet[str]
    allowed_centers: FrozenSet[int]
    capacity: int
    current_load: int
    is_active: bool
    mentor_type: MentorType
    special_schools: FrozenSet[int]
    manager_id: int | None

