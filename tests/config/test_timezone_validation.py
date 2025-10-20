from __future__ import annotations

import pytest
from pydantic import ValidationError

from sma.phase6_import_to_sabt.app.config import AppConfig


def test_invalid_tz_rejected_persian_error() -> None:
    with pytest.raises(ValidationError) as excinfo:
        AppConfig(
            redis={"dsn": "redis://localhost:6379/0"},
            database={"dsn": "postgresql://localhost/import_to_sabt"},
            auth={
                "metrics_token": "metrics-token",
                "service_token": "service-token",
                "tokens_env_var": "TOKENS",
                "download_signing_keys_env_var": "DOWNLOAD_KEYS",
                "download_url_ttl_seconds": 900,
            },
            timezone="Asia/Invalid-City",
        )
    message = str(excinfo.value)
    assert "CONFIG_TZ_INVALID" in message
    assert "مقدار TIMEZONE نامعتبر" in message

