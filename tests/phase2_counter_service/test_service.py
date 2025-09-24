# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from src.infrastructure.persistence.models import CounterSequenceModel
from src.phase2_counter_service.errors import CounterServiceError
from src.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX

from .conftest import seed_student


def _metric_value(counter, **labels):
    sample = counter.labels(**labels)
    return sample._value.get()  # type: ignore[attr-defined]


def test_assign_counter_generates_new_value(service, meters, session):
    seed_student(session, national_id="1234567890", gender=0)
    counter = service.assign_counter("1234567890", 0, "25")
    assert COUNTER_PATTERN.fullmatch(counter)
    assert counter.startswith("25" + COUNTER_PREFIX[0])
    assert _metric_value(meters._generated, result="success_0") == 1


def test_assign_counter_reuses_existing(service, meters, session):
    seed_student(session, national_id="1234567891", gender=1, counter="253731234")
    counter = service.assign_counter("1234567891", 1, "25")
    assert counter == "253731234"
    assert _metric_value(meters._generated, result="reuse_1") == 1


def test_invalid_national_id_raises(service, meters):
    with pytest.raises(CounterServiceError) as exc:
        service.assign_counter("۱۱۱", 0, "25")
    assert exc.value.detail.code == "E_INVALID_NID"
    assert _metric_value(meters._validation, code="E_INVALID_NID") == 1


def test_sequence_exhaustion(service, meters, session):
    seed_student(session, national_id="1234567892", gender=0)
    session.add(CounterSequenceModel(year_code="25", gender_code=COUNTER_PREFIX[0], last_seq=9999))
    session.commit()
    with pytest.raises(CounterServiceError) as exc:
        service.assign_counter("1234567892", 0, "25")
    assert exc.value.detail.code == "E_COUNTER_EXHAUSTED"
    assert _metric_value(meters._sequence_exhausted, year_code="25", gender="0") == 1


def test_conflict_metric_emitted(service, meters, session, fault_injector):
    fault_injector.duplicate_counter = 1
    seed_student(session, national_id="1234567893", gender=1)
    counter = service.assign_counter("1234567893", 1, "25")
    assert COUNTER_PATTERN.fullmatch(counter)
    assert _metric_value(meters._conflicts, type="counter") == 1


def test_prefix_mismatch_logged(service, meters, session, caplog):
    mismatched_counter = "253571234"
    seed_student(session, national_id="1234567894", gender=0, counter=mismatched_counter)

    with caplog.at_level("WARNING"):
        counter = service.assign_counter("1234567894", 0, "25")

    assert counter == mismatched_counter
    warnings = [record for record in caplog.records if "counter_prefix_mismatch" in record.getMessage()]
    assert warnings, "prefix mismatch should be logged"
    hashed = service.hash_fn("1234567894")
    message = warnings[0].getMessage()
    assert hashed in message
    assert "1234567894" not in message
