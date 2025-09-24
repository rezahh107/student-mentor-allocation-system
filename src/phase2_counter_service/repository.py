# -*- coding: utf-8 -*-
"""SQLAlchemy repository implementation for counter assignment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence, Tuple, cast

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.persistence.models import CounterSequenceModel, StudentModel

from .errors import CounterServiceError, db_conflict, invalid_national_id
from .types import CounterRepository, GenderLiteral
from .validation import COUNTER_PREFIX, ensure_counter_format, ensure_sequence_bounds


@dataclass(slots=True)
class FaultInjector:
    """Deterministic fault injection toggles used only in tests."""

    duplicate_counter: int = 0
    duplicate_national_id: int = 0
    sequence_race: int = 0

    def raise_if(self, name: str) -> None:
        remaining = getattr(self, name, 0)
        if remaining > 0:
            setattr(self, name, remaining - 1)
            raise IntegrityError(f"fault:{name}", params={}, orig=RuntimeError(name))


class SqlAlchemyCounterRepository(CounterRepository):
    """Concrete repository backed by SQLAlchemy sessions."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        fault_injector: Optional[FaultInjector] = None,
        max_retries: int = 3,
    ) -> None:
        self._session_factory = session_factory
        self._faults = fault_injector or FaultInjector()
        self._max_retries = max_retries

    # Public API -----------------------------------------------------------
    def fetch_student_counter(self, national_id: str) -> Optional[str]:
        with self._session_factory() as session:
            row = session.execute(
                select(StudentModel.counter).where(StudentModel.national_id == national_id)
            ).scalar_one_or_none()
            if row:
                return ensure_counter_format(row)
            return None

    def reserve_and_bind(
        self,
        national_id: str,
        gender: GenderLiteral,
        year_code: str,
        *,
        retry_on_conflict: bool = True,
        on_conflict: Optional[Callable[[str], None]] = None,
    ) -> str:
        attempt = 0
        while True:
            attempt += 1
            with self._session_factory() as session:
                try:
                    counter = self._reserve_once(session, national_id, gender, year_code)
                    session.commit()
                    return counter
                except CounterServiceError:
                    session.rollback()
                    raise
                except IntegrityError as exc:
                    session.rollback()
                    conflict_type = self._classify_conflict(exc)
                    if on_conflict is not None:
                        on_conflict(conflict_type)
                    if not retry_on_conflict or attempt >= self._max_retries:
                        raise db_conflict(f"conflict_type={conflict_type}", cause=exc) from exc
                    existing = self.fetch_student_counter(national_id)
                    if existing:
                        return existing
                    continue

    def fetch_existing_counters(self, national_ids: Sequence[str]) -> Mapping[str, str]:
        if not national_ids:
            return {}
        with self._session_factory() as session:
            stmt = select(StudentModel.national_id, StudentModel.counter).where(
                StudentModel.national_id.in_(list(national_ids))
            )
            rows = session.execute(stmt).all()
            return {nid: ensure_counter_format(counter) for nid, counter in rows if counter}

    def snapshot_sequences(self) -> Mapping[Tuple[str, str], int]:
        with self._session_factory() as session:
            stmt = select(CounterSequenceModel.year_code, CounterSequenceModel.gender_code, CounterSequenceModel.last_seq)
            return {(row.year_code, row.gender_code): int(row.last_seq) for row in session.execute(stmt)}

    # Internal helpers ----------------------------------------------------
    def _reserve_once(
        self,
        session: Session,
        national_id: str,
        gender: GenderLiteral,
        year_code: str,
    ) -> str:
        student = self._lock_student(session, national_id)
        existing_counter = cast(Optional[str], student.counter)
        if existing_counter:
            return ensure_counter_format(existing_counter)

        prefix = COUNTER_PREFIX[gender]
        seq = self._next_sequence(session, year_code, prefix)
        ensure_sequence_bounds(seq)
        counter = ensure_counter_format(f"{year_code}{prefix}{seq:04d}")

        setattr(student, "counter", counter)
        with session.begin_nested():
            self._faults.raise_if("duplicate_counter")
            session.flush()
        return counter

    def _lock_student(self, session: Session, national_id: str) -> StudentModel:
        stmt: Select[Tuple[StudentModel]] = select(StudentModel).where(StudentModel.national_id == national_id)
        if session.bind and session.bind.dialect.name != "sqlite":  # pragma: no branch - dialect guard
            stmt = stmt.with_for_update()
        try:
            result = session.execute(stmt).scalar_one()
        except NoResultFound as exc:  # pragma: no cover - defensive
            raise invalid_national_id("دانش‌آموز وجود ندارد.") from exc
        return result

    def _next_sequence(self, session: Session, year_code: str, prefix: str) -> int:
        for _ in range(self._max_retries):
            seq_row = self._select_sequence_row(session, year_code, prefix)
            if seq_row is None:
                with session.begin_nested():
                    session.add(CounterSequenceModel(year_code=year_code, gender_code=prefix, last_seq=0))
                    self._faults.raise_if("sequence_race")
                    session.flush()
                seq_row = self._select_sequence_row(session, year_code, prefix)
                if seq_row is None:
                    continue
            with session.begin_nested():
                next_value = ensure_sequence_bounds(int(seq_row.last_seq) + 1)
                setattr(seq_row, "last_seq", next_value)
                self._faults.raise_if("duplicate_national_id")
                session.flush()
            return next_value
        raise db_conflict("Could not fetch sequence row after retries")

    def _select_sequence_row(
        self, session: Session, year_code: str, prefix: str
    ) -> Optional[CounterSequenceModel]:
        stmt = select(CounterSequenceModel).where(
            CounterSequenceModel.year_code == year_code,
            CounterSequenceModel.gender_code == prefix,
        )
        if session.bind and session.bind.dialect.name != "sqlite":  # pragma: no branch
            stmt = stmt.with_for_update()
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _classify_conflict(exc: IntegrityError) -> str:
        message = str(exc.orig or exc)
        if "کد_ملی" in message or "national_id" in message or "fault:duplicate_national_id" in message:
            return "national_id"
        if "شمارنده" in message or "counter" in message or "fault:duplicate_counter" in message:
            return "counter"
        if "fault:sequence_race" in message or "sequence_race" in message:
            return "sequence"
        return "unknown"
