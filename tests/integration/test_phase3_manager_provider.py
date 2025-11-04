from __future__ import annotations

from typing import FrozenSet

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sma.infrastructure.persistence.models import (
    Base,
    ManagerAllowedCenterModel,
    ManagerModel,
)
from sma.phase3_allocation.contracts import AllocationConfig
from sma.phase3_allocation.factories import build_allocation_engine
from sma.phase3_allocation.providers import SpecialSchoolsProvider

from tests.phase3.conftest import DummyMentor, DummyStudent


class _NullSpecialSchoolsProvider(SpecialSchoolsProvider):
    def get(self, year: int) -> FrozenSet[int] | None:  # noqa: D401 - protocol contract
        return None


@pytest.fixture
def session_factory(tmp_path):
    database = tmp_path / "manager_provider.sqlite"
    engine = create_engine(f"sqlite:///{database}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


def _seed_manager(session, manager_id: int, *, centers: tuple[int, ...], active: bool = True) -> None:
    manager = ManagerModel(
        manager_id=manager_id,
        full_name=f"مدیر {manager_id}",
        email=None,
        phone=None,
        is_active=active,
    )
    session.add(manager)
    for center in centers:
        session.add(ManagerAllowedCenterModel(manager_id=manager_id, center_code=center))
    session.commit()


def test_manager_gate_allows_authorized_center(session_factory) -> None:
    with session_factory() as session:
        _seed_manager(session, 44, centers=(2,))

    engine = build_allocation_engine(
        session_factory,
        special_schools_provider=_NullSpecialSchoolsProvider(),
        config=AllocationConfig(),
    )

    student = DummyStudent(gender=0, group_code="A", reg_center=2, reg_status=0)
    mentor = DummyMentor(
        mentor_id=501,
        gender=0,
        allowed_groups=["A"],
        allowed_centers=[2],
        capacity=5,
        current_load=1,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=44,
    )

    best, trace = engine.evaluate(student, [mentor])
    assert best is mentor
    manager_checks = [entry for entry in trace[0].trace if entry["code"] == "MANAGER_CENTER_GATE"]
    assert manager_checks and manager_checks[0]["passed"] is True


def test_manager_gate_blocks_unlisted_center(session_factory) -> None:
    with session_factory() as session:
        _seed_manager(session, 55, centers=(0,))

    engine = build_allocation_engine(
        session_factory,
        special_schools_provider=_NullSpecialSchoolsProvider(),
        config=AllocationConfig(),
    )

    student = DummyStudent(gender=1, group_code="B", reg_center=2, reg_status=1)
    mentor = DummyMentor(
        mentor_id=777,
        gender=1,
        allowed_groups=["B"],
        allowed_centers=[2],
        capacity=4,
        current_load=0,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=55,
    )

    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    manager_checks = [entry for entry in trace[0].trace if entry["code"] == "MANAGER_CENTER_GATE"]
    assert manager_checks and manager_checks[0]["passed"] is False
    assert manager_checks[0]["details"]["reg_center"] == 2


def test_manager_gate_reports_missing_manager(session_factory) -> None:
    engine = build_allocation_engine(
        session_factory,
        special_schools_provider=_NullSpecialSchoolsProvider(),
        config=AllocationConfig(),
    )

    student = DummyStudent(gender=0, group_code="A", reg_center=1, reg_status=0)
    mentor = DummyMentor(
        mentor_id=888,
        gender=0,
        allowed_groups=["A"],
        allowed_centers=[1],
        capacity=6,
        current_load=2,
        is_active=True,
        mentor_type="NORMAL",
        manager_id=999,
    )

    best, trace = engine.evaluate(student, [mentor])
    assert best is None
    manager_checks = [entry for entry in trace[0].trace if entry["code"] == "MANAGER_CENTER_GATE"]
    assert manager_checks and manager_checks[0]["details"]["reason"] == "manager_centers_not_found"
