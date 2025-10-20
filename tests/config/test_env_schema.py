from __future__ import annotations

import pytest

from sma.config.env_schema import SSOConfig


def _base_env() -> dict[str, str]:
    return {
        "SSO_ENABLED": "true",
        "SSO_SESSION_TTL_SECONDS": "900",
        "SSO_BLUE_GREEN_STATE": "green",
        "OIDC_CLIENT_ID": "client",
        "OIDC_CLIENT_SECRET": "secret",
        "OIDC_ISSUER": "https://issuer",
        "OIDC_SCOPES": "openid",
    }


def test_unknown_key():
    env = _base_env()
    env["UNKNOWN"] = "value"
    with pytest.raises(ValueError) as exc:
        SSOConfig.from_env(env)
    assert "کلید ناشناخته" in str(exc.value)


def test_missing_required():
    env = _base_env()
    env.pop("OIDC_CLIENT_ID")
    with pytest.raises(ValueError) as exc:
        SSOConfig.from_env(env)
    assert "کلید الزامی" in str(exc.value)


def test_type_validation():
    env = _base_env()
    env["SSO_SESSION_TTL_SECONDS"] = "invalid"
    with pytest.raises(ValueError) as exc:
        SSOConfig.from_env(env)
    assert "نوع مقدار" in str(exc.value)
