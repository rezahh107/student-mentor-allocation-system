# -*- coding: utf-8 -*-
from __future__ import annotations

from src.phase2_counter_service.errors import CounterServiceError, db_conflict, invalid_year_code


def test_invalid_year_code_payload() -> None:
    err = invalid_year_code("کد سال باید ۲ رقم باشد")
    assert isinstance(err, CounterServiceError)
    assert err.detail.code == "E_YEAR_CODE_INVALID"
    assert "۲ رقم" in err.detail.details


def test_db_conflict_wraps_cause() -> None:
    cause = RuntimeError("duplicate")
    err = db_conflict("conflict", cause=cause)
    assert err.detail.code == "E_DB_CONFLICT"
    assert err.cause is cause
