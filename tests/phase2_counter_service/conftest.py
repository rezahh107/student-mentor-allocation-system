# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from prometheus_client import CollectorRegistry

from src.infrastructure.persistence.models import Base, CounterSequenceModel, StudentModel
from src.infrastructure.persistence.session import make_engine, make_session_factory
from src.phase2_counter_service.logging_utils import build_logger, make_hash_fn
from src.phase2_counter_service.metrics import CounterMeters
from src.phase2_counter_service.repository import FaultInjector, SqlAlchemyCounterRepository
from src.phase2_counter_service.service import CounterAssignmentService


@pytest.fixture()
def engine(tmp_path) -> Iterator:
    db_path = tmp_path / "test.sqlite"
    engine = make_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(engine) -> sessionmaker:
    return make_session_factory(engine)


@pytest.fixture()
def session(session_factory: sessionmaker) -> Iterator[Session]:
    with session_factory() as sess:
        yield sess


@pytest.fixture()
def fault_injector() -> FaultInjector:
    return FaultInjector()


@pytest.fixture()
def repository(session_factory: sessionmaker, fault_injector: FaultInjector) -> SqlAlchemyCounterRepository:
    return SqlAlchemyCounterRepository(session_factory, fault_injector=fault_injector)


@pytest.fixture()
def meters() -> CounterMeters:
    return CounterMeters(CollectorRegistry())


@pytest.fixture()
def service(repository: SqlAlchemyCounterRepository, meters: CounterMeters) -> CounterAssignmentService:
    logger = build_logger("test-counter-service")
    hash_fn = make_hash_fn("test-salt")
    return CounterAssignmentService(repository, meters, logger, hash_fn)


def seed_student(session: Session, *, national_id: str, gender: int, counter: str | None = None) -> None:
    student = StudentModel(
        national_id=national_id,
        first_name="علی",
        last_name="کاظمی",
        gender=gender,
        edu_status=0,
        reg_center=0,
        reg_status=0,
        group_code=1,
        school_code=None,
        student_type=0,
        mobile=None,
        counter=counter,
    )
    session.add(student)
    session.commit()
