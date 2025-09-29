from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.reliability.config import ReliabilitySettings


@pytest.fixture()
def base_payload(tmp_path):
    return {
        "redis": {"dsn": "redis://localhost:6379/0", "namespace": "guard"},
        "postgres": {
            "read_write_dsn": "postgresql://user:pass@localhost/db",
            "replica_dsn": "postgresql://user:pass@localhost/db",
        },
        "artifacts_root": str(tmp_path / "artifacts"),
        "backups_root": str(tmp_path / "backups"),
        "retention": {"age_days": 1, "max_total_bytes": 1024},
        "cleanup": {"part_max_age": 60, "link_ttl": 60},
        "tokens": {"metrics_read": "metrics-token"},
        "timezone": "Asia/Tehran",
        "rate_limit": {"default_rule": {"requests": 5, "window_seconds": 60}},
    }


def test_reject_unknown_keys_and_validate_tz(base_payload):
    payload = dict(base_payload)
    payload["unknown"] = "value"
    with pytest.raises(ValidationError):
        ReliabilitySettings.model_validate(payload)

    bad_tz = dict(base_payload, timezone="Not/Real")
    with pytest.raises(ValidationError):
        ReliabilitySettings.model_validate(bad_tz)

    settings = ReliabilitySettings.model_validate(base_payload)
    assert settings.redis.namespace == "guard"
    assert settings.clock().key == "Asia/Tehran"
