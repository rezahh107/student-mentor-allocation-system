# -*- coding: utf-8 -*-
"""Type definitions for the Phase 2 counter service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, Sequence, Tuple

GenderLiteral = Literal[0, 1]


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Structured Persian error payload returned to callers.

    Attributes
    ----------
    code:
        Machine-readable error code.
    message_fa:
        Persian human-facing message.
    details:
        Additional diagnostic details in English for operators.
    """

    code: str
    message_fa: str
    details: str


class LoggerLike(Protocol):
    """Protocol representing the structured logger adapter used by the service."""

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


class MeterLike(Protocol):
    """Protocol capturing the observability hooks consumed by the service."""

    def record_success(self, gender: GenderLiteral) -> None: ...

    def record_reuse(self, gender: GenderLiteral) -> None: ...

    def record_validation_error(self, code: str) -> None: ...

    def record_conflict(self, conflict_type: str) -> None: ...

    def record_failure(self, reason: str) -> None: ...

    def record_sequence_exhausted(self, year_code: str, gender: GenderLiteral) -> None: ...

    def exporter_health(self, value: float) -> None: ...


class HashFunc(Protocol):
    """PII hashing hook injected for structured logging."""

    def __call__(self, national_id: str) -> str: ...


class Clock(Protocol):
    """Clock protocol to simplify deterministic testing."""

    def now(self) -> float: ...


class CounterRepository(Protocol):
    """Persistence abstraction for counter operations."""

    def fetch_student_counter(self, national_id: str) -> Optional[str]: ...

    def reserve_and_bind(
        self,
        national_id: str,
        gender: GenderLiteral,
        year_code: str,
        *,
        retry_on_conflict: bool = True,
        on_conflict: Optional[Callable[[str], None]] = None,
    ) -> str: ...

    def fetch_existing_counters(self, national_ids: Sequence[str]) -> Mapping[str, str]: ...

    def snapshot_sequences(self) -> Mapping[Tuple[str, str], int]: ...


class BackfillObserver(Protocol):
    """Observer used to emit progress during streaming backfill."""

    def on_chunk(self, chunk_index: int, applied: int, reused: int, skipped: int) -> None: ...


class ArtifactValidator(Protocol):
    """Protocol for artifact validation functions."""

    def __call__(self) -> None: ...
