from __future__ import annotations

import pathlib

import pytest
from fastapi import FastAPI

from sma.repo_doctor.healthcheck import HealthDoctor, MIDDLEWARE_EXPECTED_ORDER
from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.logging_utils import JsonLogger
from sma.repo_doctor.metrics import DoctorMetrics
from sma.repo_doctor.retry import RetryPolicy


class RateLimit:
    pass


class Idempotency:
    pass


class Auth:
    pass


def build_doctor(tmp_path: pathlib.Path) -> HealthDoctor:
    return HealthDoctor(
        root=tmp_path,
        apply=False,
        logger=JsonLogger(tmp_path / "reports" / "mw.ndjson", tehran_clock()),
        metrics=DoctorMetrics(tmp_path / "reports" / "mw.prom"),
        retry=RetryPolicy(),
        clock=tehran_clock(),
    )


def test_middleware_order(tmp_path: pathlib.Path) -> None:
    app = FastAPI()
    app.add_middleware(RateLimit)
    app.add_middleware(Idempotency)
    app.add_middleware(Auth)

    doctor = build_doctor(tmp_path)
    order = doctor._middleware_order(app)
    assert order[:3] == MIDDLEWARE_EXPECTED_ORDER


def test_middleware_order_violation(tmp_path: pathlib.Path) -> None:
    app = FastAPI()
    app.add_middleware(Auth)
    app.add_middleware(RateLimit)
    app.add_middleware(Idempotency)

    doctor = build_doctor(tmp_path)
    with pytest.raises(AssertionError):
        doctor._middleware_order(app)
