from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.persistence.models import Base, MentorModel, OutboxMessageModel, StudentModel
from src.phase3_allocation.allocation_tx import (
    AllocationRequest,
    AtomicAllocator,
    PolicyEngine,
    PolicyVerdict,
    SimpleAllocationSequenceProvider,
)
from src.phase3_allocation.outbox import OutboxDispatcher, SystemClock
from src.phase3_allocation.uow import SQLAlchemyUnitOfWork


class CapturePublisher:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:  # noqa: D401
        self.events.append({"event_type": event_type, "payload": payload, "headers": headers})


class AlwaysApprovePolicy(PolicyEngine):
    def evaluate(self, *, student, mentor, request):  # type: ignore[override]
        return PolicyVerdict(approved=True, code="POLICY_OK", details={})


def _seed_reference_data(session: Session) -> None:
    session.add(
        StudentModel(
            national_id="0012345678",
            first_name="علی",
            last_name="نمونه",
            gender=1,
            edu_status=1,
            reg_center=1,
            reg_status=1,
            group_code=1,
            student_type=1,
        )
    )
    session.add(
        MentorModel(
            mentor_id=42,
            name="منتور نمونه",
            gender=1,
            type="عادی",
            capacity=5,
            current_load=0,
            is_active=True,
        )
    )
    session.commit()


def test_atomic_allocation_flow(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alloc_flow.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    with SessionFactory() as session:
        _seed_reference_data(session)

    clock = SystemClock()
    provider = SimpleAllocationSequenceProvider(clock=clock)

    def _uow_factory() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory=SessionFactory)

    allocator = AtomicAllocator(
        uow_factory=_uow_factory,
        sequence_provider=provider,
        policy_engine=AlwaysApprovePolicy(),
        clock=clock,
    )

    request = AllocationRequest(
        studentId="۰۰۱۲۳۴۵۶۷۸",
        mentorId=42,
        requestId="REQ-1",
        payload={"note": "تست"},
    )
    result = allocator.allocate(request)
    assert result.status == "OK"
    assert result.allocation_id is not None

    publisher = CapturePublisher()
    with SessionFactory() as session:
        dispatcher = OutboxDispatcher(
            session=session,
            publisher=publisher,
            clock=clock,
        )
        dispatched = dispatcher.dispatch_once()
        assert dispatched == 1
        event_id = publisher.events[0]["headers"]["x-event-id"]
        message = session.execute(
            select(OutboxMessageModel).where(OutboxMessageModel.event_id == event_id)
        ).scalar_one()
        assert message.status == "SENT"

    assert publisher.events[0]["payload"]["status"] == "CONFIRMED"
