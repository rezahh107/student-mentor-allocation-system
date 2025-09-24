# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.persistence.models import StudentModel
from src.phase2_counter_service.errors import CounterServiceError
from src.phase2_counter_service.repository import FaultInjector, SqlAlchemyCounterRepository
from src.phase2_counter_service.validation import COUNTER_PREFIX

from .conftest import seed_student


def test_reserve_returns_existing_counter(repository: SqlAlchemyCounterRepository, session: Session) -> None:
    seed_student(session, national_id="7777777777", gender=0, counter="253731234")
    counter = repository.reserve_and_bind("7777777777", 0, "25")
    assert counter == "253731234"


def test_reserve_conflict_exhausts(repository: SqlAlchemyCounterRepository, session: Session, fault_injector: FaultInjector) -> None:
    seed_student(session, national_id="8888888888", gender=1)
    fault_injector.duplicate_counter = repository._max_retries + 1

    with pytest.raises(CounterServiceError) as exc:
        repository.reserve_and_bind("8888888888", 1, "25")

    assert exc.value.detail.code == "E_DB_CONFLICT"


def test_reserve_conflict_returns_existing(
    repository: SqlAlchemyCounterRepository,
    session_factory: sessionmaker,
    session: Session,
    fault_injector: FaultInjector,
    monkeypatch,
) -> None:
    seed_student(session, national_id="9999999990", gender=0)
    fault_injector.duplicate_counter = 1

    original_fetch = repository.fetch_student_counter
    injected: dict[str, bool] = {"done": False}

    def fake_fetch(national_id: str) -> str | None:
        if not injected["done"]:
            with session_factory() as other_session:
                row = other_session.get(StudentModel, national_id)
                assert row is not None
                row.counter = "253731200"
                other_session.commit()
            injected["done"] = True
        return original_fetch(national_id)

    monkeypatch.setattr(repository, "fetch_student_counter", fake_fetch)

    counter = repository.reserve_and_bind("9999999990", 0, "25")
    assert counter == "253731200"


def test_fetch_existing_counters_empty(repository: SqlAlchemyCounterRepository) -> None:
    assert repository.fetch_existing_counters([]) == {}


def test_lock_student_with_for_update(
    repository: SqlAlchemyCounterRepository,
    session_factory: sessionmaker,
    session: Session,
) -> None:
    seed_student(session, national_id="5555555554", gender=1)
    with session_factory() as local_session:
        local_session.bind.dialect.name = "postgresql"
        row = repository._lock_student(local_session, "5555555554")
        assert row.national_id == "5555555554"


def test_select_sequence_row_for_update(
    repository: SqlAlchemyCounterRepository,
    session_factory: sessionmaker,
) -> None:
    with session_factory() as local_session:
        local_session.bind.dialect.name = "postgresql"
        result = repository._select_sequence_row(local_session, "25", COUNTER_PREFIX[0])
        assert result is None


def test_next_sequence_retries_when_row_missing(
    repository: SqlAlchemyCounterRepository,
    session_factory: sessionmaker,
    monkeypatch,
) -> None:
    calls = {"count": 0}
    original_select = repository._select_sequence_row

    def fake_select(session: Session, year_code: str, prefix: str):
        calls["count"] += 1
        if calls["count"] <= 2:
            return None
        return original_select(session, year_code, prefix)

    monkeypatch.setattr(repository, "_select_sequence_row", fake_select)

    with session_factory() as local_session:
        value = repository._next_sequence(local_session, "25", COUNTER_PREFIX[0])

    assert value == 1
    assert calls["count"] >= 3


def test_next_sequence_raises_after_retries(
    session_factory: sessionmaker,
    monkeypatch,
) -> None:
    repo = SqlAlchemyCounterRepository(session_factory, fault_injector=FaultInjector(), max_retries=1)

    def always_none(session: Session, year_code: str, prefix: str):  # noqa: ARG001
        return None

    monkeypatch.setattr(repo, "_select_sequence_row", always_none)

    with session_factory() as local_session:
        with pytest.raises(CounterServiceError) as exc:
            repo._next_sequence(local_session, "25", COUNTER_PREFIX[0])

    assert exc.value.detail.code == "E_DB_CONFLICT"
