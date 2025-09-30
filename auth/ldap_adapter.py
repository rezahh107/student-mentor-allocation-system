from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping

from .errors import ProviderError
from .metrics import AuthMetrics
from .utils import exponential_backoff, fold_digits, masked, sanitize_scope

LOGGER = logging.getLogger("sso.ldap")
@dataclass(slots=True)
class LdapSettings:
    timeout_seconds: float = 3.0
    group_rules: Mapping[str, tuple[str, str]] | None = None


class LdapGroupMapper:
    """Resolve role/center_scope pairs using LDAP group membership."""

    def __init__(
        self,
        fetch_groups: Callable[[str], Awaitable[Iterable[str]]],
        *,
        settings: LdapSettings,
        metrics: AuthMetrics | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 0.1,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._fetch_groups = fetch_groups
        self._settings = settings
        self._metrics = metrics
        self._max_retries = max(1, max_retries)
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep or asyncio.sleep

    async def __call__(
        self,
        claims: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> tuple[str, str]:
        user = str(claims.get("sub") or claims.get("NameID") or "")
        groups = claims.get("groups")
        if not groups:
            groups = await self._safe_fetch(user, rid=correlation_id or masked(user))
        if isinstance(groups, str):
            group_list = [groups]
        else:
            group_list = list(groups)
        role, scope = self._apply_rules(group_list)
        LOGGER.info(
            "LDAP_GROUP_MAPPED",
            extra={
                "user": masked(user),
                "role": role,
                "scope": scope,
            },
        )
        return role, scope

    async def _safe_fetch(self, user: str, *, rid: str) -> Iterable[str]:
        if not user:
            raise ProviderError(
                code="AUTH_FORBIDDEN",
                message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
                reason="missing_user",
            )
        reason = "timeout"
        for attempt in range(1, self._max_retries + 1):
            try:
                return await asyncio.wait_for(
                    self._fetch_groups(user),
                    timeout=self._settings.timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                if attempt == self._max_retries:
                    if self._metrics:
                        self._metrics.retry_exhaustion_total.labels(adapter="ldap", reason=reason).inc()
                    message = "پاسخ‌گویی سرویس دایرکتوری به‌موقع نبود؛ بعداً تلاش کنید."
                    raise ProviderError(
                        code="AUTH_LDAP_TIMEOUT",
                        message_fa=message,
                        reason="timeout",
                    ) from exc
                if self._metrics:
                    self._metrics.retry_attempts_total.labels(adapter="ldap", reason=reason).inc()
                delay = exponential_backoff(
                    self._backoff_seconds,
                    attempt,
                    jitter_seed=f"{rid}:{reason}",
                )
                if self._metrics:
                    self._metrics.retry_backoff_seconds.labels(adapter="ldap", reason=reason).observe(delay)
                await self._sleep(delay)

    def _apply_rules(self, groups: Iterable[str]) -> tuple[str, str]:
        rules = self._settings.group_rules or {}
        for group in groups:
            group_key = fold_digits(str(group).strip()) or ""
            if not group_key:
                continue
            if group_key in rules:
                role, scope = rules[group_key]
                if role not in {"ADMIN", "MANAGER"}:
                    continue
                scope = "ALL" if role == "ADMIN" else sanitize_scope(scope)
                return role, scope
            if ":" in group_key:
                role_candidate, scope_candidate = group_key.split(":", 1)
                role_candidate = role_candidate.upper()
                if role_candidate in {"ADMIN", "MANAGER"}:
                    try:
                        scope = "ALL" if role_candidate == "ADMIN" else sanitize_scope(scope_candidate)
                        return role_candidate, scope
                    except ValueError:  # noqa: BLE001
                        continue
        raise ProviderError(
            code="AUTH_FORBIDDEN",
            message_fa="دسترسی مجاز نیست؛ نقش یا اسکوپ کافی نیست.",
            reason="no_matching_group",
        )


__all__ = ["LdapGroupMapper", "LdapSettings"]
