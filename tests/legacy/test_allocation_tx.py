from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sma.phase3_allocation.allocation_tx import AllocationRequest, SimpleAllocationSequenceProvider
from sma.phase3_allocation.idempotency import derive_idempotency_key


class _FixedClock:
    def __init__(self, year: int) -> None:
        self._year = year

    def now(self) -> datetime:
        return datetime(self._year, 3, 21, tzinfo=timezone.utc)


@dataclass
class _FakeSession:
    value: int | None

    def execute(self, _stmt: object) -> SimpleNamespace:
        return SimpleNamespace(scalar=lambda: self.value)


def test_allocation_request_aliases_normalize_digits() -> None:
    request = AllocationRequest.model_validate(
        {
            "studentId": "\u200c۱۲۳۴۵۰۰۱ ",
            "mentorId": "۰۰۷۷",
            "requestId": "  req-۷۷  ",
            "payload": '{"notes":"ثبت‌شده"}',
            "metadata": '{"source":"csv"}',
            "yearCode": "۱۴۰۲",
        }
    )

    assert request.student_id == "12345001"
    assert request.mentor_id == 77
    assert request.request_id == "req-77"
    assert request.payload["notes"] == "ثبت‌شده"
    assert request.metadata["source"] == "csv"
    assert request.year_code == "۱۴۰۲"


def test_idempotency_key_stable_for_aliases() -> None:
    first = derive_idempotency_key(
        student_id="۱۲۳۴۵",
        mentor_id="۰۰۷۷",
        request_id="  req-۷۷  ",
        payload={"scores": [1, 2, 3]},
    )
    second = derive_idempotency_key(
        student_id="12345",
        mentor_id="0077",
        request_id="req-77",
        payload={"scores": [1, 2, 3]},
    )
    assert first == second


def test_sequence_provider_uses_year_code_padding() -> None:
    clock = _FixedClock(year=2027)
    provider = SimpleAllocationSequenceProvider(clock=clock, legacy_width=6)

    first_session = _FakeSession(value=None)
    first = provider.next(session=first_session, student=object(), mentor=object())
    assert first.allocation_id == 1
    assert first.year_code == "27"
    assert first.allocation_code == "27000001"

    second_session = _FakeSession(value=first.allocation_id)
    second = provider.next(session=second_session, student=object(), mentor=object())
    assert second.allocation_id == 2
    assert second.allocation_code.endswith("000002")
