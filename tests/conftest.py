from __future__ import annotations

import pathlib
from typing import Iterator

import pytest
from prometheus_client import CollectorRegistry

from src.fakeredis import FakeStrictRedis
from src.repo_doctor.clock import tehran_clock
from src.repo_doctor.metrics import DoctorMetrics


def pytest_addoption(parser):
    parser.addini("env", type="linelist", help="environment variables for tests")


@pytest.fixture()
def tehran_frozen_clock():
    return tehran_clock()


@pytest.fixture()
def metrics_registry(tmp_path: pathlib.Path) -> Iterator[DoctorMetrics]:
    metrics = DoctorMetrics(tmp_path / "metrics.prom")
    yield metrics
    metrics.registry = CollectorRegistry()


@pytest.fixture()
def fake_redis() -> Iterator[FakeStrictRedis]:
    client = FakeStrictRedis()
    client.flushdb()
    yield client
    client.flushdb()
