from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Mapping
from xml.etree import ElementTree as ET

from sma.reliability.clock import Clock

from .errors import AuthError, ProviderError
from .metrics import AuthMetrics
from .models import BridgeSession
from .session_store import SessionStore
from .utils import hash_identifier, log_event, masked, sanitize_scope

LOGGER = logging.getLogger("sso.saml")


@dataclass(slots=True)
class SAMLSettings:
    sp_entity_id: str
    idp_metadata_xml: str
    certificate_pem: str
    private_key_pem: str
    audience: str


class SAMLAdapter:
    def __init__(
        self,
        settings: SAMLSettings,
        *,
        session_store: SessionStore,
        metrics: AuthMetrics,
        clock: Clock,
        audit_sink: Callable[[str, str, Mapping[str, Any]], Awaitable[None]],
        ldap_mapper: Callable[[Mapping[str, Any]], Awaitable[tuple[str, str]]] | None = None,
        max_assertion_kb: int = 250,
    ) -> None:
        self._settings = settings
        self._session_store = session_store
        self._metrics = metrics
        self._clock = clock
        self._audit_sink = audit_sink
        self._ldap_mapper = ldap_mapper
        self._max_assertion_bytes = max_assertion_kb * 1024

    async def authenticate(
        self,
        *,
        assertion: str,
        correlation_id: str,
        request_id: str,
    ) -> BridgeSession:
        histogram = self._metrics.duration_seconds.labels(provider="saml")
        with histogram.time():
            try:
                attributes = self._parse_assertion(assertion)
                role, scope = await self._map_attributes(attributes, correlation_id)
                subject = str(attributes.get("NameID", "anonymous"))
                session = await self._session_store.create(
                    correlation_id=correlation_id,
                    subject=subject,
                    role=role,
                    center_scope=scope,
                )
                await self._audit("AUTHN_OK", correlation_id, request_id, role=role, scope=scope)
                self._metrics.ok_total.labels(provider="saml").inc()
                log_event(
                    LOGGER,
                    msg="SAML_AUTH_OK",
                    rid=request_id,
                    cid=masked(correlation_id),
                    role=role,
                )
                return session
            except AuthError as exc:
                self._metrics.fail_total.labels(provider="saml", reason=exc.reason).inc()
                await self._audit("AUTHN_FAIL", correlation_id, request_id, error=exc.reason)
                log_event(
                    LOGGER,
                    msg="SAML_AUTH_FAIL",
                    rid=request_id,
                    cid=masked(correlation_id),
                    error=exc.reason,
                )
                raise

    def _parse_assertion(self, assertion: str) -> Mapping[str, Any]:
        data = textwrap.dedent(assertion.strip())
        encoded = data.encode("utf-8")
        if len(encoded) > self._max_assertion_bytes:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="پیام هویتی بسیار بزرگ است.",
                reason="assertion_too_large",
            )
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:  # noqa: BLE001
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="پیام هویتی نامعتبر است.",
                reason="parse_error",
            ) from exc
        conditions = root.find(".//{*}Conditions")
        if conditions is None:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="پیام هویتی شرایط ندارد.",
                reason="missing_conditions",
            )
        self._validate_conditions(conditions)
        attributes: dict[str, Any] = {}
        name_id = root.findtext(".//{*}NameID")
        if name_id:
            attributes["NameID"] = name_id
        for attr in root.findall(".//{*}Attribute"):
            key = attr.get("Name") or attr.get("FriendlyName")
            if not key:
                continue
            values = [value.text or "" for value in attr.findall("{*}AttributeValue")]
            attributes[key] = values[0] if len(values) == 1 else values
        return attributes

    def _validate_conditions(self, conditions: ET.Element) -> None:
        audience = conditions.findtext(".//{*}Audience")
        if audience != self._settings.audience:
            raise ProviderError(
                code="AUTH_IDP_ERROR",
                message_fa="شناسهٔ مخاطب همخوانی ندارد.",
                reason="invalid_audience",
            )
        not_before = conditions.get("NotBefore")
        not_on_or_after = conditions.get("NotOnOrAfter")
        now = self._clock.now()
        if not_before:
            start = self._parse_datetime(not_before)
            if now < start:
                raise ProviderError(
                    code="AUTH_IDP_ERROR",
                    message_fa="پیام هویتی هنوز معتبر نیست.",
                    reason="not_before",
                )
        if not_on_or_after:
            end = self._parse_datetime(not_on_or_after)
            if now >= end:
                raise ProviderError(
                    code="AUTH_IDP_ERROR",
                    message_fa="پیام هویتی منقضی شده است.",
                    reason="expired",
                )

    async def _map_attributes(
        self,
        attributes: Mapping[str, Any],
        correlation_id: str,
    ) -> tuple[str, str]:
        role_raw = str(attributes.get("role") or "").strip().upper()
        scope_raw = attributes.get("center_scope")
        if self._ldap_mapper:
            role_raw, scope_raw = await self._ldap_mapper(attributes, correlation_id=correlation_id)
        if role_raw not in {"ADMIN", "MANAGER"}:
            raise ProviderError(
                code="AUTH_FORBIDDEN",
                message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
                reason="invalid_role",
            )
        try:
            scope = "ALL" if role_raw == "ADMIN" else sanitize_scope(str(scope_raw) if scope_raw is not None else "")
        except ValueError as exc:  # noqa: BLE001
            raise ProviderError(
                code="AUTH_FORBIDDEN",
                message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
                reason="invalid_scope",
            ) from exc
        return role_raw, scope

    async def _audit(self, action: str, correlation_id: str, request_id: str, **fields: Any) -> None:
        payload = {
            "action": action,
            "cid": hash_identifier(correlation_id),
            "request_id": request_id,
            **fields,
            "ts": self._clock.now().isoformat(),
        }
        await self._audit_sink(action, correlation_id, payload)

    def _parse_datetime(self, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)


__all__ = ["SAMLAdapter", "SAMLSettings"]
