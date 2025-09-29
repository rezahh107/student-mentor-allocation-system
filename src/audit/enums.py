"""Enumerations for audit events."""
from __future__ import annotations

from enum import Enum


class AuditActorRole(str, Enum):
    """Actor role attached to the audit event."""

    ADMIN = "ADMIN"
    MANAGER = "MANAGER"


class AuditAction(str, Enum):
    """Audit taxonomy for governance actions."""

    UPLOAD_CREATED = "UPLOAD_CREATED"
    UPLOAD_VALIDATED = "UPLOAD_VALIDATED"
    UPLOAD_ACTIVATED = "UPLOAD_ACTIVATED"
    EXPORT_STARTED = "EXPORT_STARTED"
    EXPORT_FINALIZED = "EXPORT_FINALIZED"
    EXPORT_DOWNLOADED = "EXPORT_DOWNLOADED"
    AUTHN_OK = "AUTHN_OK"
    AUTHN_FAIL = "AUTHN_FAIL"
    CONFIG_REJECTED = "CONFIG_REJECTED"


class AuditOutcome(str, Enum):
    """Result of the audited operation."""

    OK = "OK"
    ERROR = "ERROR"


__all__ = ["AuditActorRole", "AuditAction", "AuditOutcome"]
