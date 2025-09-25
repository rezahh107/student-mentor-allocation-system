from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.infrastructure.persistence.models import Base, OutboxMessageModel
from src.phase3_allocation.outbox import BackoffPolicy, OutboxDispatcher, OutboxEvent, SystemClock


def test_outbox_event_rejects_large_payload() -> None:
    payload = {"data": "x" * 40000}
    event = OutboxEvent(
        event_id="evt",
        aggregate_type="Allocation",
        aggregate_id="1",
        event_type="MentorAssigned",
        payload=payload,
        occurred_at=datetime.now(timezone.utc),
        available_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError) as exc:
        event.to_model()
    assert str(exc.value).startswith("PAYLOAD_TOO_LARGE|")


def test_outbox_event_rejects_invalid_status() -> None:
    event = OutboxEvent(
        event_id="evt",
        aggregate_type="Allocation",
        aggregate_id="1",
        event_type="MentorAssigned",
        payload={},
        occurred_at=datetime.now(timezone.utc),
        available_at=datetime.now(timezone.utc),
        status="UNKNOWN",  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError) as exc:
        event.to_model()
    assert str(exc.value).startswith("OUTBOX_STATUS_INVALID|")


def test_dispatcher_marks_failed_after_max_retries(tmp_path, caplog) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.sqlite'}", future=True)
    Base.metadata.create_all(engine, tables=[OutboxMessageModel.__table__])
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = Session()
    now = datetime.now(timezone.utc)
    model = OutboxMessageModel(
        id="row",
        event_id="evt-1",
        aggregate_type="Allocation",
        aggregate_id="1",
        event_type="MentorAssigned",
        payload_json='{"idempotency_key": "abc"}',
        occurred_at=now,
        available_at=now - timedelta(seconds=5),
        retry_count=1,
        status="PENDING",
    )
    session.add(model)
    session.commit()

    statuses: list[tuple[str, str]] = []

    class ExplodingPublisher:
        def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:  # noqa: D401
            raise RuntimeError("boom")

    dispatcher = OutboxDispatcher(
        session=session,
        publisher=ExplodingPublisher(),
        clock=SystemClock(),
        backoff=BackoffPolicy(max_retries=1),
        status_hook=lambda event_id, status, extra: statuses.append((event_id, status)),
    )

    with caplog.at_level("ERROR"):
        dispatcher.dispatch_once()

    session.refresh(model)
    assert model.status == "FAILED"
    assert model.last_error and "MAX_RETRIES_REACHED" in model.last_error
    assert ("evt-1", "FAILED") in statuses
    assert any("MAX_RETRIES_REACHED" in record.message for record in caplog.records)
