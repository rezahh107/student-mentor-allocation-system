from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Iterable, Optional

COUNTER_PREFIX = {0: "373", 1: "357"}


class ExportErrorCode(str, Enum):
    EXPORT_VALIDATION_ERROR = "EXPORT_VALIDATION_ERROR"
    EXPORT_IO_ERROR = "EXPORT_IO_ERROR"
    EXPORT_EMPTY = "EXPORT_EMPTY"
    EXPORT_PROFILE_UNKNOWN = "EXPORT_PROFILE_UNKNOWN"


@dataclass(frozen=True)
class ExportProfile:
    """Represents a versioned export profile configuration."""

    name: str
    version: str
    sensitive_columns: tuple[str, ...]
    excel_risky_columns: tuple[str, ...]

    @property
    def full_name(self) -> str:
        return f"{self.name}_{self.version}"


SABT_V1_PROFILE = ExportProfile(
    name="SABT",
    version="V1",
    sensitive_columns=(
        "national_id",
        "counter",
        "mobile",
        "mentor_id",
        "school_code",
    ),
    excel_risky_columns=(
        "first_name",
        "last_name",
        "mentor_name",
    ),
)


@dataclass(frozen=True)
class ExportSnapshot:
    marker: str
    created_at: datetime


@dataclass(frozen=True)
class ExportDeltaWindow:
    created_at_watermark: datetime
    id_watermark: int


@dataclass(frozen=True)
class ExportFilters:
    year: int
    center: Optional[int] = None
    delta: Optional[ExportDeltaWindow] = None


@dataclass(frozen=True)
class ExportOptions:
    chunk_size: int = 50_000
    include_bom: bool = False
    newline: str = "\r\n"
    excel_mode: bool = True


@dataclass(frozen=True)
class NormalizedStudentRow:
    national_id: str
    counter: str
    first_name: str
    last_name: str
    gender: int
    mobile: str
    reg_center: int
    reg_status: int
    group_code: int
    student_type: int
    school_code: Optional[int]
    mentor_id: Optional[str]
    mentor_name: Optional[str]
    mentor_mobile: Optional[str]
    allocation_date: datetime
    year_code: str
    created_at: datetime
    id: int


@dataclass(frozen=True)
class ExportManifestFile:
    name: str
    sha256: str
    row_count: int
    byte_size: int


@dataclass(frozen=True)
class ExportManifest:
    profile: ExportProfile
    filters: ExportFilters
    snapshot: ExportSnapshot
    generated_at: datetime
    total_rows: int
    files: tuple[ExportManifestFile, ...]
    delta_window: Optional[ExportDeltaWindow] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExportJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class ExportJob:
    id: str
    status: ExportJobStatus
    filters: ExportFilters
    options: ExportOptions
    snapshot: ExportSnapshot
    namespace: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    manifest: Optional[ExportManifest] = None
    error: Optional[str] = None


Clock = Callable[[], datetime]


class ExporterDataSource:
    """Abstract interface for fetching normalized rows."""

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot) -> Iterable[NormalizedStudentRow]:
        raise NotImplementedError


class SpecialSchoolsRoster:
    def is_special(self, year: int, school_code: Optional[int]) -> bool:
        raise NotImplementedError


class RedisLike:
    def setnx(self, key: str, value: str, ex: int | None = None) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def hset(self, key: str, mapping: dict[str, Any]) -> None:
        raise NotImplementedError

    def hgetall(self, key: str) -> dict[str, str]:
        raise NotImplementedError

    def expire(self, key: str, ttl: int) -> None:
        raise NotImplementedError


class StorageBackend:
    def ensure_directory(self, path: str) -> None:
        raise NotImplementedError

    def cleanup_partials(self, path: str) -> None:
        raise NotImplementedError


class SignedURLProvider:
    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        raise NotImplementedError
