from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping

from auth.ldap_adapter import LdapSettings
from auth.oidc_adapter import OIDCSettings
from auth.saml_adapter import SAMLSettings


@dataclass(slots=True)
class SSOConfig:
    enabled: bool
    session_ttl_seconds: int
    blue_green_state: str
    oidc: OIDCSettings | None
    saml: SAMLSettings | None
    ldap: LdapSettings | None

    @property
    def post_ready(self) -> bool:
        return self.blue_green_state in {"green", "active"}

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "SSOConfig":
        mutable = dict(env)
        _reject_unknown(mutable.keys())
        enabled = _read_bool(mutable.get("SSO_ENABLED", "false"), "SSO_ENABLED")
        ttl_seconds = _read_int(mutable.get("SSO_SESSION_TTL_SECONDS", "900"), "SSO_SESSION_TTL_SECONDS")
        blue_green_state = mutable.get("SSO_BLUE_GREEN_STATE", "blue").lower()
        if blue_green_state not in {"blue", "green", "active", "warming"}:
            raise ValueError(f"«نوع مقدار نامعتبر است: SSO_BLUE_GREEN_STATE»")

        oidc = _parse_oidc(mutable) if enabled else None
        saml = _parse_saml(mutable) if enabled else None
        if enabled and not (oidc or saml):
            raise ValueError("«کلید الزامی مفقود: OIDC_CLIENT_ID|SAML_SP_ENTITY_ID»")
        ldap = _parse_ldap(mutable)
        return cls(
            enabled=enabled,
            session_ttl_seconds=ttl_seconds,
            blue_green_state=blue_green_state,
            oidc=oidc,
            saml=saml,
            ldap=ldap,
        )


_ALLOWED_KEYS = {
    "SSO_ENABLED",
    "SSO_SESSION_TTL_SECONDS",
    "SSO_BLUE_GREEN_STATE",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_ISSUER",
    "OIDC_SCOPES",
    "OIDC_TOKEN_ENDPOINT",
    "OIDC_AUTH_ENDPOINT",
    "OIDC_JWKS_ENDPOINT",
    "SAML_SP_ENTITY_ID",
    "SAML_IDP_METADATA_XML",
    "SAML_SP_CERT_PEM",
    "SAML_SP_KEY_PEM",
    "SAML_AUDIENCE",
    "LDAP_URL",
    "LDAP_BIND_DN",
    "LDAP_BIND_PASSWORD",
    "LDAP_BASE_DN",
    "LDAP_GROUP_ATTR",
    "LDAP_TIMEOUT_SEC",
    "LDAP_GROUP_RULES",
}


def _reject_unknown(keys: Iterable[str]) -> None:
    for key in keys:
        if key not in _ALLOWED_KEYS:
            raise ValueError(f"«کلید ناشناخته: {key}»")


def _parse_oidc(env: MutableMapping[str, str]) -> OIDCSettings | None:
    client_id = env.get("OIDC_CLIENT_ID")
    client_secret = env.get("OIDC_CLIENT_SECRET")
    issuer = env.get("OIDC_ISSUER")
    scopes_raw = env.get("OIDC_SCOPES")
    token_endpoint = env.get("OIDC_TOKEN_ENDPOINT") or (f"{issuer}/token" if issuer else None)
    auth_endpoint = env.get("OIDC_AUTH_ENDPOINT") or (f"{issuer}/authorize" if issuer else None)
    jwks_endpoint = env.get("OIDC_JWKS_ENDPOINT") or (f"{issuer}/jwks" if issuer else None)
    required = {
        "OIDC_CLIENT_ID": client_id,
        "OIDC_CLIENT_SECRET": client_secret,
        "OIDC_ISSUER": issuer,
        "OIDC_SCOPES": scopes_raw,
    }
    if not any(required.values()):
        return None
    for key, value in required.items():
        if not value:
            raise ValueError(f"«کلید الزامی مفقود: {key}»")
    scopes = tuple(part for part in scopes_raw.split() if part)
    if not scopes:
        raise ValueError("«نوع مقدار نامعتبر است: OIDC_SCOPES»")
    return OIDCSettings(
        client_id=client_id,
        client_secret=client_secret,
        issuer=issuer.rstrip("/"),
        token_endpoint=token_endpoint or f"{issuer}/token",
        jwks_endpoint=jwks_endpoint or f"{issuer}/jwks",
        auth_endpoint=auth_endpoint or f"{issuer}/authorize",
        scopes=scopes,
    )


def _parse_saml(env: MutableMapping[str, str]) -> SAMLSettings | None:
    entity_id = env.get("SAML_SP_ENTITY_ID")
    metadata_xml = env.get("SAML_IDP_METADATA_XML")
    cert_pem = env.get("SAML_SP_CERT_PEM")
    key_pem = env.get("SAML_SP_KEY_PEM")
    audience = env.get("SAML_AUDIENCE") or entity_id
    if not entity_id and not metadata_xml:
        return None
    required = {
        "SAML_SP_ENTITY_ID": entity_id,
        "SAML_IDP_METADATA_XML": metadata_xml,
        "SAML_SP_CERT_PEM": cert_pem,
        "SAML_SP_KEY_PEM": key_pem,
    }
    for key, value in required.items():
        if not value:
            raise ValueError(f"«کلید الزامی مفقود: {key}»")
    return SAMLSettings(
        sp_entity_id=entity_id,
        idp_metadata_xml=metadata_xml,
        certificate_pem=cert_pem,
        private_key_pem=key_pem,
        audience=audience or entity_id,
    )


def _parse_ldap(env: MutableMapping[str, str]) -> LdapSettings | None:
    timeout = env.get("LDAP_TIMEOUT_SEC")
    rules_raw = env.get("LDAP_GROUP_RULES")
    if not any(key.startswith("LDAP_") for key in env):
        return None
    group_rules: dict[str, tuple[str, str]] = {}
    if rules_raw:
        for item in rules_raw.split(","):
            if not item.strip():
                continue
            try:
                group, role, scope = item.split(":", 2)
            except ValueError as exc:  # noqa: BLE001
                raise ValueError("«نوع مقدار نامعتبر است: LDAP_GROUP_RULES»") from exc
            group_rules[group.strip()] = (role.strip().upper(), scope.strip())
    try:
        timeout_value = float(timeout) if timeout else 3.0
    except ValueError as exc:  # noqa: BLE001
        raise ValueError("«نوع مقدار نامعتبر است: LDAP_TIMEOUT_SEC»") from exc
    return LdapSettings(timeout_seconds=timeout_value, group_rules=group_rules)


def _read_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no", ""}:
        return False
    raise ValueError(f"«نوع مقدار نامعتبر است: {key}»")


def _read_int(value: str, key: str) -> int:
    try:
        return int(value)
    except ValueError as exc:  # noqa: BLE001
        raise ValueError(f"«نوع مقدار نامعتبر است: {key}»") from exc


__all__ = ["SSOConfig"]
