from __future__ import annotations

import pytest

from windows_service.controller import _validate_environment
from windows_service.errors import ServiceError


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in ("DATABASE_URL", "REDIS_URL", "METRICS_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    yield
    for key in ("DATABASE_URL", "REDIS_URL", "METRICS_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def test_missing_env_messages(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("METRICS_TOKEN", "metrics")
    with pytest.raises(ServiceError) as captured:
        _validate_environment()
    err = captured.value
    assert err.code == "CONFIG_MISSING"
    assert err.message == "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است."
    assert err.context == {"variable": "DATABASE_URL"}


def test_null_like_env_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "none")
    monkeypatch.setenv("METRICS_TOKEN", "metrics")
    with pytest.raises(ServiceError) as captured:
        _validate_environment()
    assert captured.value.context == {"variable": "REDIS_URL"}
    assert "متغیر REDIS_URL" in captured.value.message


def test_zero_string_is_accepted(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("METRICS_TOKEN", "0")
    env = _validate_environment()
    assert env["METRICS_TOKEN"] == "0"


def test_digit_folding_and_control_removal(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres\u200c")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/۰")
    monkeypatch.setenv("METRICS_TOKEN", "\u200f metrics\u0007")
    env = _validate_environment()
    assert env["REDIS_URL"].endswith("/0")
    assert env["METRICS_TOKEN"] == "metrics"
