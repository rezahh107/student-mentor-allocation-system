# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID, uuid4

from sma.core.clock import tehran_clock

_CLOCK = tehran_clock()

@dataclass(slots=True)
class DomainEvent:
    event_id: UUID
    event_type: str
    version: int
    occurred_at: datetime
    correlation_id: str
    causation_id: str
    tenant: str
    year: int
    payload: dict[str, Any]

    @staticmethod
    def now(event_type: str, payload: dict[str, Any], *, version: int = 1,
            correlation_id: str = "", causation_id: str = "",
            tenant: str = "foundation", year: int = 1404) -> "DomainEvent":
        return DomainEvent(
            event_id=uuid4(),
            event_type=event_type,
            version=version,
            occurred_at=_CLOCK.now(),
            correlation_id=correlation_id,
            causation_id=causation_id,
            tenant=tenant,
            year=year,
            payload=payload,
        )


# Typed factories for main events
def StudentImported(**payload: Any) -> DomainEvent:
    return DomainEvent.now("StudentImported", payload)


def CounterGenerated(**payload: Any) -> DomainEvent:
    return DomainEvent.now("CounterGenerated", payload)


def MentorAssigned(**payload: Any) -> DomainEvent:
    return DomainEvent.now("MentorAssigned", payload)


def AllocationFailed(**payload: Any) -> DomainEvent:
    return DomainEvent.now("AllocationFailed", payload)

