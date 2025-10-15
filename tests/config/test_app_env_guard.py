from __future__ import annotations

import pytest

from phase6_import_to_sabt.app.config import AppConfig


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = (
        "REDIS_URL",
        "DATABASE_URL",
        "METRICS_TOKEN",
        "SIGNING_KEY_HEX",
        "IMPORT_TO_SABT_REDIS",
        "IMPORT_TO_SABT_DATABASE",
        "IMPORT_TO_SABT_AUTH",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def _populate_minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    monkeypatch.setenv("SIGNING_KEY_HEX", "a" * 64)
    monkeypatch.setenv("METRICS_TOKEN", "dev-metrics")
    monkeypatch.setenv("IMPORT_TO_SABT_AUTH", '{"service_token":"dev-admin"}')


def test_from_env_uses_sane_defaults(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    _populate_minimal_env(monkeypatch)
    config = AppConfig.from_env()
    assert config.redis.dsn == "redis://localhost:6379/0"
    assert config.database.dsn == "postgresql://postgres:postgres@localhost:5432/postgres"
    assert config.auth.metrics_token == "dev-metrics"


def test_missing_signing_key_raises(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    _populate_minimal_env(monkeypatch)
    monkeypatch.delenv("SIGNING_KEY_HEX", raising=False)
    with pytest.raises(ValueError) as exc:
        AppConfig.from_env()
    assert "SIGNING_KEY_HEX" in str(exc.value)


def test_invalid_redis_url(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    _populate_minimal_env(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "http://localhost:1234")
    with pytest.raises(ValueError) as exc:
        AppConfig.from_env()
    assert "REDIS_URL" in str(exc.value)


def test_invalid_database_url(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    _populate_minimal_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "mysql://localhost/test")
    with pytest.raises(ValueError) as exc:
        AppConfig.from_env()
    assert "DATABASE_URL" in str(exc.value)
