from __future__ import annotations

import pytest

from sma.config.env_schema import SSOConfig


def test_config_guard_rejection_unknown_key():
    env = {
        "SSO_ENABLED": "true",
        "SSO_SESSION_TTL_SECONDS": "900",
        "SSO_BLUE_GREEN_STATE": "green",
        "UNKNOWN_KEY": "x",
    }
    with pytest.raises(ValueError) as exc:
        SSOConfig.from_env(env)
    assert "کلید ناشناخته" in str(exc.value)
