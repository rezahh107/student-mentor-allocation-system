from __future__ import annotations

import threading
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.infrastructure.persistence.models import (
    AllocationRecord,
    Base,
    MentorModel,
    OutboxMessageModel,
    StudentModel,
)
from src.phase3_allocation.allocation_tx import (
    AllocationIdentifiers,
    AllocationRequest,
    AllocationSequenceProvider,
    AtomicAllocator,
    PolicyEngine,
    PolicyVerdict,
)
from src.phase3_allocation.outbox import BackoffPolicy, OutboxDispatcher
from src.phase3_allocation.uow import SQLAlchemyUnitOfWork


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._wall = start or datetime(2025, 1, 1, tzinfo=timezone.utc)
        self._mono = 0.0
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._wall

    def monotonic(self) -> float:
        with self._lock:
            return self._mono

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._wall += timedelta(seconds=seconds)
            self._mono += seconds


class StubPolicy(PolicyEngine):
    def __init__(self, approve: bool = True) -> None:
        self.approve = approve
        self.calls: list[tuple[str, int]] = []

    def evaluate(self, *, student: StudentModel, mentor: MentorModel, request: AllocationRequest) -> PolicyVerdict:  # type: ignore[override]
        self.calls.append((student.national_id, mentor.mentor_id))
        if self.approve:
            return PolicyVerdict(approved=True, code="POLICY_OK", details={})
        return PolicyVerdict(approved=False, code="POLICY_DENIED", details={})


class StubSequence(AllocationSequenceProvider):
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.counter = 1000
        self.lock = threading.Lock()

    def next(self, *, session: Session, student: StudentModel, mentor: MentorModel) -> AllocationIdentifiers:
        with self.lock:
            self.counter += 1
            allocation_id = self.counter
        year_code = f"{self.clock.now().year % 100:02d}"
        return AllocationIdentifiers(
            allocation_id=allocation_id,
            year_code=year_code,
            allocation_code=f"{year_code}{allocation_id:06d}",
        )


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / "alloc.db"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def seed_base_data(session: Session) -> None:
    student = StudentModel(
        national_id="0012345678",
        first_name="علی",
        last_name="رضایی",
        gender=1,
        edu_status=1,
        reg_center=1,
        reg_status=1,
        group_code=101,
        school_code=5001,
        student_type=0,
    )
    mentor = MentorModel(
        mentor_id=42,
        name="Mentor",
        gender=1,
        type="عادی",
        capacity=10,
        current_load=0,
        is_active=True,
    )
    session.add_all([student, mentor])
    session.commit()


def build_allocator(session_factory, clock: FakeClock, policy: PolicyEngine | None = None) -> AtomicAllocator:
    sequence = StubSequence(clock)

    def factory():
        return SQLAlchemyUnitOfWork(session_factory=session_factory)

    return AtomicAllocator(
        uow_factory=factory,
        sequence_provider=sequence,
        policy_engine=policy or StubPolicy(),
        clock=clock,
    )


def test_concurrent_allocation_single_row(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(
        studentId="۰۰۱۲۳۴۵۶۷۸",  # Persian digits + leading zeros
        mentorId="۴۲",
        requestId="REQ-۱",
        payload={"source": "test"},
    )

    results: list = []

    def worker():
        results.append(allocator.allocate(request))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with session_factory() as session:
        count_alloc = session.execute(select(AllocationRecord)).scalars().all()
        count_outbox = session.execute(select(OutboxMessageModel)).scalars().all()

    assert len(count_alloc) == 1
    assert len(count_outbox) == 1
    assert results[0].allocation_id == results[1].allocation_id
    assert results[0].status in {"OK", "ALREADY_ASSIGNED"}
    assert results[1].status in {"OK", "ALREADY_ASSIGNED"}


def test_idempotent_replay_returns_previous(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(
        studentId="0012345678",
        mentorId="42",
        requestId="req-1",
        payload={"attempt": 1},
    )
    first = allocator.allocate(request)
    second = allocator.allocate(request)
    assert first.allocation_id == second.allocation_id
    assert second.status == "ALREADY_ASSIGNED"
    assert first.idempotency_key == second.idempotency_key


def test_unique_student_year_conflict_returns_existing(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request1 = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    result1 = allocator.allocate(request1)
    request2 = AllocationRequest(studentId="0012345678", mentorId="42", payload={"cycle": 2})
    result2 = allocator.allocate(request2)
    assert result1.allocation_id == result2.allocation_id
    assert result2.status == "ALREADY_ASSIGNED"


def test_policy_reject_blocks_allocation(session_factory) -> None:
    clock = FakeClock()
    policy = StubPolicy(approve=False)
    allocator = build_allocator(session_factory, clock, policy=policy)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    result = allocator.allocate(request)
    assert result.status == "POLICY_REJECT"
    with session_factory() as session:
        rows = session.execute(select(AllocationRecord)).scalars().all()
        assert rows == []


def test_dry_run_skips_persistence(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    result = allocator.allocate(request, dry_run=True)
    assert result.dry_run is True
    with session_factory() as session:
        assert session.execute(select(AllocationRecord)).scalars().all() == []


def test_outbox_retry_and_success(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    allocator.allocate(request)

    class FailingPublisher:
        def __init__(self) -> None:
            self.calls = 0

        def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")

    publisher = FailingPublisher()
    session = session_factory()
    dispatcher = OutboxDispatcher(
        session=session,
        publisher=publisher,
        clock=clock,
        backoff=BackoffPolicy(base_seconds=1, cap_seconds=300, max_retries=5),
        batch_size=10,
    )

    sent = dispatcher.dispatch_once()
    assert sent == 0
    clock.advance(2)
    sent = dispatcher.dispatch_once()
    assert sent == 1

    with session_factory() as check_session:
        event = check_session.execute(select(OutboxMessageModel)).scalar_one()
        assert event.status == "SENT"
        assert event.retry_count == 1


def test_outbox_poison_marks_failed(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    allocator.allocate(request)

    class AlwaysFailPublisher:
        def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
            raise RuntimeError("boom")

    session = session_factory()
    dispatcher = OutboxDispatcher(
        session=session,
        publisher=AlwaysFailPublisher(),
        clock=clock,
        backoff=BackoffPolicy(base_seconds=1, cap_seconds=5, max_retries=2),
        batch_size=1,
    )

    for _ in range(3):
        dispatcher.dispatch_once()
        clock.advance(5)

    with session_factory() as check_session:
        event = check_session.execute(select(OutboxMessageModel)).scalar_one()
        assert event.status == "FAILED"
        assert event.retry_count == 3


def test_dispatcher_resume_after_restart(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", payload={})
    allocator.allocate(request)

    class FailFirstPublisher:
        def __init__(self) -> None:
            self.failed = False

        def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
            if not self.failed:
                self.failed = True
                raise RuntimeError("fail once")

    session = session_factory()
    publisher = FailFirstPublisher()
    dispatcher = OutboxDispatcher(
        session=session,
        publisher=publisher,
        clock=clock,
        backoff=BackoffPolicy(base_seconds=1, cap_seconds=5, max_retries=3),
    )

    dispatcher.dispatch_once()
    session.close()

    clock.advance(2)
    new_session = session_factory()
    dispatcher = OutboxDispatcher(
        session=new_session,
        publisher=publisher,
        clock=clock,
        backoff=BackoffPolicy(base_seconds=1, cap_seconds=5, max_retries=3),
    )
    dispatcher.dispatch_once()

    with session_factory() as check_session:
        event = check_session.execute(select(OutboxMessageModel)).scalar_one()
        assert event.status == "SENT"


def test_event_payload_shape(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(studentId="0012345678", mentorId="42", requestId="REQ-1", payload={"foo": "bar"})
    result = allocator.allocate(request)

    with session_factory() as session:
        event = session.execute(select(OutboxMessageModel)).scalar_one()
        payload = json.loads(event.payload_json)

    assert payload == {
        "event_id": result.outbox_event_id,
        "allocation_id": result.allocation_id,
        "allocation_code": result.allocation_code,
        "year_code": result.year_code,
        "student_id": "0012345678",
        "mentor_id": 42,
        "idempotency_key": result.idempotency_key,
        "status": "CONFIRMED",
        "occurred_at": payload["occurred_at"],
    }


def test_request_validation_handles_zero_width(session_factory) -> None:
    clock = FakeClock()
    allocator = build_allocator(session_factory, clock)
    with session_factory() as session:
        seed_base_data(session)

    request = AllocationRequest(
        studentId="\u200c0012345678",
        mentorId="۴۲",
        requestId="\u200cREQ",
        payload="{\"a\":1}",
    )
    result = allocator.allocate(request)
    assert result.status == "OK"

