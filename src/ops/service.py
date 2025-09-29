from __future__ import annotations

"""Service layer for rendering ops dashboards."""

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from .replica_adapter import ReplicaAdapter


@dataclass(frozen=True)
class OpsContext:
    role: str
    center_scope: str | None
    correlation_id: str


class OpsService:
    """High level API used by FastAPI handlers."""

    def __init__(self, replica: ReplicaAdapter) -> None:
        self._replica = replica

    _EXPORT_BADGES = {
        "pending": "در انتظار",
        "queued": "در انتظار",
        "running": "در حال پردازش",
        "processing": "در حال پردازش",
        "completed": "موفق",
        "succeeded": "موفق",
        "failed": "ناموفق",
        "errored": "ناموفق",
    }
    _UPLOAD_BADGES = {
        "starting": "در حال آغاز",
        "started": "در حال آغاز",
        "validating": "در حال بررسی",
        "uploading": "در حال بارگذاری",
        "completed": "موفق",
        "failed": "ناموفق",
        "queued": "در انتظار",
    }
    _SENSITIVE_TOKENS = ("name", "national", "email", "phone", "mobile", "identifier")

    async def load_exports(self, ctx: OpsContext) -> Dict[str, Any]:
        result = await self._replica.fetch_exports(center=ctx.center_scope if ctx.role == "MANAGER" else None)
        return {
            "rows": self._shape_rows(result.rows, kind="exports"),
            "generated_at": result.generated_at,
        }

    async def load_uploads(self, ctx: OpsContext) -> Dict[str, Any]:
        result = await self._replica.fetch_uploads(center=ctx.center_scope if ctx.role == "MANAGER" else None)
        return {
            "rows": self._shape_rows(result.rows, kind="uploads"),
            "generated_at": result.generated_at,
        }

    def _shape_rows(self, rows: Sequence[Mapping[str, Any]], *, kind: str) -> List[Dict[str, Any]]:
        shaped: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            shaped.append(self._sanitize_row(row, kind=kind, ordinal=index))
        return shaped

    def _sanitize_row(self, row: Mapping[str, Any], *, kind: str, ordinal: int) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {"row": ordinal}
        for key, value in row.items():
            lowered = key.lower()
            if any(token in lowered for token in self._SENSITIVE_TOKENS):
                continue
            sanitized[key] = value
        if kind == "exports":
            sanitized["status_badge"] = self._badge_value(
                row.get("status") or row.get("status_label"),
                self._EXPORT_BADGES,
            )
        else:
            sanitized["phase_badge"] = self._badge_value(
                row.get("phase") or row.get("phase_label") or row.get("status"),
                self._UPLOAD_BADGES,
            )
        return sanitized

    @staticmethod
    def _badge_value(value: Any, mapping: Mapping[str, str]) -> str:
        if value is None:
            return "نامشخص"
        text = str(value).strip()
        normalized = text.casefold()
        return mapping.get(normalized, text)


__all__ = ["OpsService", "OpsContext"]
