from __future__ import annotations

import pytest

from windows_service.controller import _validate_environment
from windows_service.errors import ServiceError


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    yield
    for key in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)


def test_missing_env_messages(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with pytest.raises(ServiceError) as captured:
        _validate_environment()
    err = captured.value
    assert err.code == "CONFIG_MISSING"
    assert err.message == "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است."
    assert err.context == {"variable": "DATABASE_URL"}


def test_null_like_env_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "none")
    with pytest.raises(ServiceError) as captured:
        _validate_environment()
    assert captured.value.context == {"variable": "REDIS_URL"}
    assert "متغیر REDIS_URL" in captured.value.message


def test_basic_env_validation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    env = _validate_environment()
    assert env["DATABASE_URL"].startswith("postgresql://")
    assert env["REDIS_URL"].endswith("/0")


def test_digit_folding_and_control_removal(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres\u200c")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/۰")
    env = _validate_environment()
    assert env["REDIS_URL"].endswith("/0")
