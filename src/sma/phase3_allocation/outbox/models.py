"""Domain models used by the outbox subsystem."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sma.infrastructure.persistence.models import OutboxMessageModel

from .backoff import BackoffPolicy
from .clock import Clock

OutboxStatus = Literal["PENDING", "SENT", "FAILED"]
_MAX_PAYLOAD_BYTES = 32768


@dataclass(slots=True)
class OutboxEvent:
    """Outbox event representation persisted atomically with allocations."""

    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict
    occurred_at: datetime
    available_at: datetime
    retry_count: int = 0
    status: OutboxStatus = "PENDING"

    def to_model(self) -> OutboxMessageModel:
        """Convert the event into a SQLAlchemy persistence model."""

        payload_json = json.dumps(self.payload, ensure_ascii=False)
        payload_size = len(payload_json.encode("utf-8"))
        if payload_size > _MAX_PAYLOAD_BYTES:
            raise ValueError("PAYLOAD_TOO_LARGE|اندازه محتوای رویداد بیش از حد مجاز است")
        if self.status not in ("PENDING", "SENT", "FAILED"):
            raise ValueError("OUTBOX_STATUS_INVALID|وضعیت نامعتبر برای پیام اوتباکس")
        if self.retry_count < 0:
            raise ValueError("NEGATIVE_RETRY_COUNT|تعداد تلاش نباید منفی باشد")
        model = OutboxMessageModel(
            event_id=self.event_id,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            event_type=self.event_type,
            payload_json=payload_json,
            occurred_at=self.occurred_at,
            available_at=self.available_at,
            retry_count=self.retry_count,
            status=self.status,
        )
        return model


@dataclass(slots=True)
class OutboxMessage:
    """Wrapper around ``OutboxMessageModel`` with scheduling helpers."""

    model: OutboxMessageModel

    def compute_next_available_at(
        self,
        *,
        clock: Clock,
        backoff: BackoffPolicy,
    ) -> tuple[datetime, float, float, float]:
        """Compute the next ``available_at`` timestamp using monotonic timing.

        Returns a tuple of ``(next_available_at, delay_seconds, skew_seconds)`` where
        ``skew_seconds`` captures the difference between wall-clock elapsed time and
        monotonic elapsed time in order to surface clock drift handling.
        """

        mono_before = clock.monotonic()
        wall_before = clock.now()

        delay = backoff.next_delay(self.model.retry_count)
        target_mono = mono_before + delay

        mono_after = clock.monotonic()
        wall_after = clock.now()

        elapsed_wall = (wall_after - wall_before).total_seconds()
        elapsed_mono = mono_after - mono_before
        skew_seconds = elapsed_wall - elapsed_mono

        remaining = target_mono - mono_after
        if remaining <= 0:
            remaining = backoff.base_seconds
        next_available_at = wall_after + timedelta(seconds=remaining)
        return next_available_at, delay, skew_seconds, remaining

    @property
    def status(self) -> OutboxStatus:
        return self.model.status  # type: ignore[return-value]

    @status.setter
    def status(self, value: OutboxStatus) -> None:
        if value not in ("PENDING", "SENT", "FAILED"):
            raise ValueError("OUTBOX_STATUS_INVALID|وضعیت نامعتبر برای پیام اوتباکس")
        self.model.status = value
