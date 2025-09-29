"""Convenience helpers for emitting governance audit events."""
from __future__ import annotations

from typing import Mapping

from src.phase7_release.config_guard import ConfigGuard, ConfigValidationError, ResolvedConfig

from .enums import AuditAction, AuditActorRole, AuditOutcome
from .service import AuditService


async def record_config_rejected(
    service: AuditService,
    *,
    actor_role: AuditActorRole,
    center_scope: str | None,
    resource_type: str,
    resource_id: str,
    request_id: str,
    error_code: str,
) -> None:
    await service.record_event(
        actor_role=actor_role,
        center_scope=center_scope,
        action=AuditAction.CONFIG_REJECTED,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        outcome=AuditOutcome.ERROR,
        error_code=error_code,
    )


async def audited_config_parse(
    guard: ConfigGuard,
    payload: Mapping[str, object],
    *,
    service: AuditService,
    actor_role: AuditActorRole,
    center_scope: str | None,
    resource_type: str,
    resource_id: str,
    request_id: str,
) -> ResolvedConfig:
    """Parse configuration while emitting CONFIG_REJECTED on failures."""

    try:
        return guard.parse(payload)
    except ConfigValidationError as error:
        error_code = _derive_config_error_code(error)
        await record_config_rejected(
            service,
            actor_role=actor_role,
            center_scope=center_scope,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            error_code=error_code,
        )
        service.log_failure(
            rid=request_id,
            op="config-guard",
            namespace="phase7.release.config",
            error=error,
        )
        raise


def _derive_config_error_code(error: ConfigValidationError) -> str:
    message = str(error)
    if "کلید ناشناخته" in message:
        return "CONFIG_UNKNOWN_KEY"
    if "متغیر محیطی" in message:
        return "CONFIG_MISSING_ENV"
    if "مسیر بسیار طولانی" in message:
        return "CONFIG_PATH_TOO_LONG"
    if "مقدار نامعتبر" in message or "unsupported-profile" in message:
        return "CONFIG_INVALID_VALUE"
    return "CONFIG_VALIDATION_FAILED"


__all__ = ["record_config_rejected", "audited_config_parse"]
