# -*- coding: utf-8 -*-
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from src.phase2_counter_service.validation import COUNTER_PATTERN

from .conftest import seed_student


def _metric_value(counter, **labels):
    sample = counter.labels(**labels)
    return sample._value.get()  # type: ignore[attr-defined]


def test_duplicate_national_id_conflict(service, meters, session, fault_injector):
    fault_injector.duplicate_national_id = 1
    seed_student(session, national_id="2234567890", gender=0)
    counter = service.assign_counter("2234567890", 0, "25")
    assert COUNTER_PATTERN.fullmatch(counter)
    assert _metric_value(meters._conflicts, type="national_id") == 1


def test_sequence_race_conflict(service, meters, session, fault_injector):
    fault_injector.sequence_race = 1
    seed_student(session, national_id="2234567891", gender=1)
    counter = service.assign_counter("2234567891", 1, "25")
    assert COUNTER_PATTERN.fullmatch(counter)
    assert _metric_value(meters._conflicts, type="sequence") == 1


def test_unknown_conflict_branch(service, meters, session, caplog):
    seed_student(session, national_id="3234567891", gender=1)

    class UnknownFault:
        def __init__(self) -> None:
            self._remaining = 1

        def raise_if(self, name: str) -> None:  # noqa: D401 - test helper
            if self._remaining and name == "duplicate_counter":
                self._remaining -= 1
                raise IntegrityError("weird_integrity", params={}, orig=RuntimeError("unknown"))

    service.repository._faults = UnknownFault()  # type: ignore[attr-defined]

    with caplog.at_level("WARNING"):
        counter = service.assign_counter("3234567891", 1, "25")

    assert COUNTER_PATTERN.fullmatch(counter)
    assert _metric_value(meters._conflicts, type="unknown") == 1
    assert any("conflict_resolved" in record.message for record in caplog.records)
    assert any("E_DB_CONFLICT" in record.message for record in caplog.records)
