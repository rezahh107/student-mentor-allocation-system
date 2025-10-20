"""Audit exporters for CSV/JSON with Excel-safe streaming."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from sma.phase7_release.hashing import sha256_file

from .enums import AuditAction, AuditActorRole, AuditOutcome
from .release_manifest import ReleaseManifest, make_manifest_entry
from .repository import AuditQuery
from .service import AuditEventRecord, AuditMetrics, AuditService


@dataclass(slots=True)
class ExportResult:
    path: Path
    sha256: str
    size: int


class AuditExporter:
    """Coordinates streaming exports to disk and clients."""

    def __init__(
        self,
        service: AuditService,
        manifest: ReleaseManifest,
        *,
        metrics: AuditMetrics,
        exports_dir: Path,
    ) -> None:
        self._service = service
        self._manifest = manifest
        self._metrics = metrics
        self._exports_dir = exports_dir
        self._exports_dir.mkdir(parents=True, exist_ok=True)

    async def export(
        self,
        *,
        fmt: str,
        query: AuditQuery,
        bom: bool,
        rid: str,
        actor_role: AuditActorRole,
        center_scope: str | None,
        job_id: str | None = None,
    ) -> ExportResult:
        fmt = fmt.lower()
        if fmt not in {"csv", "json"}:
            raise ValueError("AUDIT_EXPORT_ERROR: فرمت نامعتبر است")
        await self._service.record_event(
            actor_role=actor_role,
            center_scope=center_scope,
            action=AuditAction.EXPORT_STARTED,
            resource_type="audit",
            resource_id="events",
            request_id=rid,
            outcome=AuditOutcome.OK,
            job_id=job_id,
        )
        try:
            if fmt == "csv":
                result = await self._export_csv(query=query, bom=bom)
                kind = "audit-export-csv"
            else:
                result = await self._export_json(query=query, bom=bom)
                kind = "audit-export-json"
            self._metrics.export_bytes_total.labels(format=fmt).inc(result.size)
            entry = make_manifest_entry(result.path, sha256=result.sha256, kind=kind, ts=self._service.now())
            self._manifest.update(entry=entry)
            await self._service.record_event(
                actor_role=actor_role,
                center_scope=center_scope,
                action=AuditAction.EXPORT_FINALIZED,
                resource_type="audit",
                resource_id=result.path.name,
                request_id=rid,
                outcome=AuditOutcome.OK,
                job_id=job_id,
                artifact_sha256=result.sha256,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            await self._service.record_event(
                actor_role=actor_role,
                center_scope=center_scope,
                action=AuditAction.EXPORT_FINALIZED,
                resource_type="audit",
                resource_id="events",
                request_id=rid,
                outcome=AuditOutcome.ERROR,
                job_id=job_id,
                error_code="EXPORT_FAILURE",
            )
            self._service.log_failure(rid=rid, op="export", namespace="audit", error=exc)
            raise

    async def _export_csv(self, *, query: AuditQuery, bom: bool) -> ExportResult:
        filename = f"audit_export_{self._service.now().strftime('%Y%m%dT%H%M%S')}.csv"
        path = self._exports_dir / filename

        async def writer(handle) -> None:
            if bom:
                handle.write("\ufeff")
            csv_writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
            csv_writer.writerow(
                [
                    "ts",
                    "actor_role",
                    "center_scope",
                    "action",
                    "resource_type",
                    "resource_id",
                    "job_id",
                    "request_id",
                    "outcome",
                    "error_code",
                    "artifact_sha256",
                ]
            )
            async for event in self._service.stream_events(query):
                csv_writer.writerow(self._csv_row(event))

        size = await _atomic_async_write(path, writer)
        digest = sha256_file(path)
        return ExportResult(path=path, sha256=digest, size=size)

    async def _export_json(self, *, query: AuditQuery, bom: bool) -> ExportResult:
        filename = f"audit_export_{self._service.now().strftime('%Y%m%dT%H%M%S')}.json"
        path = self._exports_dir / filename

        async def writer(handle) -> None:
            if bom:
                handle.write("\ufeff")
            handle.write("[")
            first = True
            async for event in self._service.stream_events(query):
                payload = json.dumps(self._json_row(event), ensure_ascii=False, separators=(",", ":"))
                if not first:
                    handle.write(",\r\n")
                handle.write(payload)
                first = False
            handle.write("]")

        size = await _atomic_async_write(path, writer)
        digest = sha256_file(path)
        return ExportResult(path=path, sha256=digest, size=size)

    def _csv_row(self, event: AuditEventRecord) -> list[str]:
        return [
            event.ts.isoformat(),
            event.actor_role.value,
            event.center_scope or "",
            event.action.value,
            self._safe_value(event.resource_type),
            self._safe_value(event.resource_id),
            self._safe_value(event.job_id or ""),
            self._safe_value(event.request_id),
            event.outcome.value,
            self._safe_value(event.error_code or ""),
            self._safe_value(event.artifact_sha256 or ""),
        ]

    def _json_row(self, event: AuditEventRecord) -> dict[str, str]:
        return {
            "id": str(event.id),
            "ts": event.ts.isoformat(),
            "actor_role": event.actor_role.value,
            "center_scope": event.center_scope or "",
            "action": event.action.value,
            "resource_type": self._safe_value(event.resource_type),
            "resource_id": self._safe_value(event.resource_id),
            "job_id": self._safe_value(event.job_id or ""),
            "request_id": self._safe_value(event.request_id),
            "outcome": event.outcome.value,
            "error_code": self._safe_value(event.error_code or ""),
            "artifact_sha256": self._safe_value(event.artifact_sha256 or ""),
        }

    @staticmethod
    def _safe_value(value: str) -> str:
        sanitized = value.replace("\u200c", "").strip()
        if sanitized and sanitized[0] in "=+-@":
            return "'" + sanitized
        return sanitized


async def _atomic_async_write(path: Path, writer: Callable[[Any], Awaitable[None]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            await writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        return path.stat().st_size
    except Exception:  # noqa: BLE001
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


__all__ = ["AuditExporter", "ExportResult"]
