from __future__ import annotations

import json

import pytest

from sma.phase6_import_to_sabt.security.config import AccessConfigGuard, ConfigGuardError


def test_reject_unknown() -> None:
    env = {
        "TOKENS_CASE": json.dumps(
            [
                {"value": "T" * 24, "role": "ADMIN", "extra": "forbidden"},
            ],
            ensure_ascii=False,
        ),
        "DOWNLOAD_CASE": json.dumps(
            [
                {"kid": "ABCD", "secret": "S" * 48, "state": "active"},
            ],
            ensure_ascii=False,
        ),
    }
    guard = AccessConfigGuard(env=env)

    with pytest.raises(ConfigGuardError) as excinfo:
        guard.load(tokens_env="TOKENS_CASE", signing_keys_env="DOWNLOAD_CASE", download_ttl_seconds=900)

    assert "کلید ناشناخته" in str(excinfo.value)
