"""Configuration loading and validation guarantees."""

from __future__ import annotations

from pathlib import Path

import pytest

from sma.ci_hardening.settings import (
    AppSettings,
    AuthSettings,
    DatabaseSettings,
    RedisSettings,
    SettingsError,
)


def test_missing_sections_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing required sections must trigger deterministic Persian errors."""

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "REDIS__HOST=localhost",
                "REDIS__PORT=6379",
                "DATABASE__DSN=postgresql://example",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SettingsError) as exc:
        AppSettings.load()
    assert "پیکربندی ناقص" in str(exc.value)


def test_safe_dict_masks_sensitive_values() -> None:
    """Sensitive fields must be masked when serialised."""

    settings = AppSettings(
        redis=RedisSettings(host="localhost", port=6379, db=0),
        database=DatabaseSettings(dsn="postgresql://user:pass@localhost/db"),
        auth=AuthSettings(service_token="secret-token", metrics_token="metrics-token"),
    )
    safe = settings.as_safe_dict()
    assert safe["database"]["dsn"] == "***"
    assert safe["auth"]["service_token"] == "***"
