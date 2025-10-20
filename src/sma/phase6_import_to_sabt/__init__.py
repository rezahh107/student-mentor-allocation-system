"""Phase-6 ImportToSabt exporter package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

_EXPORTS = {
    "ExportFilters": "phase6_import_to_sabt.models:ExportFilters",
    "ExportJobRunner": "phase6_import_to_sabt.job_runner:ExportJobRunner",
    "ExportJobStatus": "phase6_import_to_sabt.models:ExportJobStatus",
    "ExportOptions": "phase6_import_to_sabt.models:ExportOptions",
    "ExportProfile": "phase6_import_to_sabt.models:ExportProfile",
    "ExportSnapshot": "phase6_import_to_sabt.models:ExportSnapshot",
    "ImportToSabtExporter": "phase6_import_to_sabt.exporter:ImportToSabtExporter",
    "NormalizedStudentRow": "phase6_import_to_sabt.models:NormalizedStudentRow",
    "SABT_V1_PROFILE": "phase6_import_to_sabt.models:SABT_V1_PROFILE",
    "create_cli": "phase6_import_to_sabt.cli:create_cli",
    "create_export_api": "phase6_import_to_sabt.api:create_export_api",
}

if TYPE_CHECKING:  # pragma: no cover - type-checker only
    from sma.phase6_import_to_sabt.api import create_export_api as create_export_api
    from sma.phase6_import_to_sabt.cli import create_cli as create_cli
    from sma.phase6_import_to_sabt.exporter import ImportToSabtExporter as ImportToSabtExporter
    from sma.phase6_import_to_sabt.job_runner import ExportJobRunner as ExportJobRunner
    from sma.phase6_import_to_sabt.models import (
        ExportFilters as ExportFilters,
        ExportJobStatus as ExportJobStatus,
        ExportOptions as ExportOptions,
        ExportProfile as ExportProfile,
        ExportSnapshot as ExportSnapshot,
        NormalizedStudentRow as NormalizedStudentRow,
        SABT_V1_PROFILE as SABT_V1_PROFILE,
    )


def __getattr__(name: str) -> Any:
    try:
        target = _EXPORTS[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise AttributeError(name) from exc
    module_path, attr = target.split(":")
    module = import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
