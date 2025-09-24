# -*- coding: utf-8 -*-
"""Domain-level counter assignment service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .errors import CounterServiceError
from .types import CounterRepository, GenderLiteral, HashFunc, LoggerLike, MeterLike
from .validation import COUNTER_PREFIX, ensure_valid_inputs, normalize


@dataclass(slots=True)
class CounterAssignmentService:
    """Pure application service orchestrating validation, repository, and observability."""

    repository: CounterRepository
    meters: MeterLike
    logger: LoggerLike
    hash_fn: HashFunc

    def assign_counter(self, national_id: str, gender: GenderLiteral, year_code: str) -> str:
        normalized_nid: str
        normalized_year: str
        try:
            normalized_nid, normalized_year = ensure_valid_inputs(national_id, gender, year_code)
        except CounterServiceError as err:
            self.meters.record_validation_error(err.detail.code)
            self.logger.warning(
                "validation_failed",
                extra={"کد": err.detail.code, "شناسه": self.hash_fn(normalize(national_id))},
            )
            raise

        hashed_nid = self.hash_fn(normalized_nid)

        existing = self.repository.fetch_student_counter(normalized_nid)
        if existing:
            self._audit_prefix(existing, gender, normalized_year, hashed_nid)
            self.meters.record_reuse(gender)
            self.logger.info(
                "counter_reused",
                extra={"شناسه": hashed_nid, "counter": existing},
            )
            return existing

        conflict_type: Optional[str] = None

        def _on_conflict(kind: str) -> None:
            nonlocal conflict_type
            conflict_type = kind

        try:
            counter = self.repository.reserve_and_bind(
                normalized_nid,
                gender,
                normalized_year,
                on_conflict=_on_conflict,
            )
        except CounterServiceError as err:
            if err.detail.code == "E_COUNTER_EXHAUSTED":
                self.meters.record_sequence_exhausted(normalized_year, gender)
            else:
                self.meters.record_failure(err.detail.code)
            self.logger.error(
                "counter_failed",
                extra={
                    "کد": err.detail.code,
                    "جزئیات": err.detail.details,
                    "شناسه": hashed_nid,
                },
            )
            raise

        self._audit_prefix(counter, gender, normalized_year, hashed_nid)
        if conflict_type is not None:
            self.meters.record_conflict(conflict_type)
            self.logger.warning(
                "conflict_resolved",
                extra={
                    "کد": "E_DB_CONFLICT",
                    "نوع": conflict_type,
                    "شناسه": hashed_nid,
                    "counter": counter,
                },
            )
            return counter

        self.meters.record_success(gender)
        self.logger.info(
            "counter_assigned",
            extra={
                "شناسه": hashed_nid,
                "counter": counter,
                "کد_سال": normalized_year,
                "پیشوند": COUNTER_PREFIX[gender],
            },
        )
        return counter

    def _audit_prefix(
        self,
        counter: str,
        gender: GenderLiteral,
        year_code: str,
        hashed_nid: str,
    ) -> None:
        """Log a warning when persisted counters do not match expected prefix."""

        expected_prefix = f"{year_code}{COUNTER_PREFIX[gender]}"
        if not counter.startswith(expected_prefix):
            self.logger.warning(
                "counter_prefix_mismatch",
                extra={
                    "شناسه": hashed_nid,
                    "counter": counter,
                    "پیشوند_مورد_انتظار": expected_prefix,
                    "پیشوند_فعلی": counter[:5],
                },
            )
