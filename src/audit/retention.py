"""Audit data lifecycle helpers (archiving + retention enforcement)."""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.engine import Engine
from zoneinfo import ZoneInfo

from src.phase7_release.hashing import sha256_file
from src.reliability.clock import Clock

from .release_manifest import ReleaseManifest, make_manifest_entry
from .service import AuditMetrics

_LOGGER = logging.getLogger("audit.retention")
_MONTH_KEY_RE = re.compile(r"^\d{4}_\d{2}$")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ZW_CHARS = {"\u200c", "\u200d", "\u200e", "\u200f"}
_CONTROL_ORDS = {ord(chr_) for chr_ in ("\u202a", "\u202b", "\u202c", "\u202d", "\u202e")}
_PERSIAN_UNIFY = {ord("ي"): "ی", ord("ك"): "ک"}
_PERSIAN_TZ = ZoneInfo("Asia/Tehran")

_T = TypeVar("_T")


@dataclass(slots=True)
class _ArchiveRow:
    id: int
    ts_iso: str
    actor_role: str
    center_scope: str
    action: str
    resource_type: str
    resource_id: str
    job_id: str
    request_id: str
    outcome: str
    error_code: str
    artifact_sha256: str


def _compute_backoff_delay(base: float, multiplier: float, attempt: int, seed: str) -> float:
    base = max(0.0, base)
    multiplier = max(1.0, multiplier)
    scaled = base * (multiplier ** max(0, attempt - 1))
    digest = hashlib.blake2b(f"{seed}:{attempt}".encode("utf-8"), digest_size=8).digest()
    jitter_fraction = int.from_bytes(digest, "big") / float(1 << 64)
    return scaled + (scaled * 0.5 * jitter_fraction)


def _run_with_retry(
    func: Callable[[], _T],
    *,
    stage: str,
    seed: str,
    config: AuditArchiveConfig,
    metrics: AuditMetrics,
    rid: str,
    op: str,
    namespace: str,
    extra: dict[str, Any] | None = None,
) -> _T:
    attempts = max(1, config.retry_attempts)
    extra_payload = dict(extra or {})
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            metrics.retry_attempts_total.labels(stage=stage).inc()
            delay = _compute_backoff_delay(
                config.retry_base_delay_seconds,
                config.retry_multiplier,
                attempt,
                f"{seed}:{stage}",
            )
            payload = {
                "rid": rid,
                "op": op,
                "namespace": namespace,
                "stage": stage,
                "attempt": attempt,
                "max_attempts": attempts,
                "scheduled_delay_seconds": round(delay, 6),
                "last_error": repr(exc),
            }
            payload.update(extra_payload)
            _LOGGER.warning("AUDIT_RETRY_ATTEMPT", extra=payload)
            if attempt == attempts:
                metrics.retry_exhausted_total.labels(stage=stage).inc()
                _LOGGER.error("AUDIT_RETRY_EXHAUSTED", extra=payload)
                raise


@dataclass(slots=True)
class AuditArchiveWindow:
    """Inclusive start / exclusive end for a calendar month."""

    month_key: str
    start: datetime
    end: datetime


@dataclass(slots=True)
class AuditArchiveArtifact:
    path: Path
    sha256: str
    size_bytes: int


@dataclass(slots=True)
class AuditArchiveResult:
    window: AuditArchiveWindow
    csv: AuditArchiveArtifact
    json: AuditArchiveArtifact
    manifest: AuditArchiveArtifact
    row_count: int


@dataclass(slots=True)
class AuditArchiveConfig:
    """Configuration payload for archive + retention actions."""

    archive_root: Path
    csv_bom: bool = True
    manifest_schema_version: int = 1
    tool_version: str = "1.0.0"
    retention_age_days: int | None = None
    retention_age_months: int | None = None
    retention_size_bytes: int | None = None
    fetch_size: int = 1_000
    retry_attempts: int = 3
    retry_base_delay_seconds: float = 0.05
    retry_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.archive_root, str):
            self.archive_root = Path(self.archive_root)
        if self.fetch_size <= 0:
            self.fetch_size = 1
        if self.retry_attempts <= 0:
            self.retry_attempts = 1
        if self.retry_base_delay_seconds < 0:
            self.retry_base_delay_seconds = 0.0
        if self.retry_multiplier < 1:
            self.retry_multiplier = 1.0


class ArchiveFailure(RuntimeError):
    """Raised when archiving fails for deterministic Persian messaging."""


class AuditArchiver:
    """Create monthly CSV/JSON archives with manifest + metrics."""

    def __init__(
        self,
        *,
        engine: Engine,
        metrics: AuditMetrics,
        clock: Clock,
        release_manifest: ReleaseManifest,
        config: AuditArchiveConfig,
        timezone: ZoneInfo = _PERSIAN_TZ,
    ) -> None:
        self._engine = engine
        self._metrics = metrics
        self._clock = clock
        self._manifest = release_manifest
        self._config = config
        self._tz = timezone

    def archive_month(self, month_key: str, *, dry_run: bool = False) -> AuditArchiveResult:
        window = self._window(month_key)
        csv_path = self._artifact_path(window, suffix=".csv")
        json_path = self._artifact_path(window, suffix=".json")
        manifest_path = self._artifact_path(window, name="audit_archive_manifest.json")
        rid = f"audit-archive-{month_key}"
        self._cleanup_parts(window)

        if dry_run:
            row_count = _run_with_retry(
                lambda: self._count_rows(window),
                stage="archive_count",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"archive_path": str(csv_path.parent)},
            )
            now = self._clock.now().astimezone(self._tz)
            manifest_payload = self._build_manifest_payload(
                window,
                csv_artifact=AuditArchiveArtifact(csv_path, "", 0),
                json_artifact=AuditArchiveArtifact(json_path, "", 0),
                manifest_path=manifest_path,
                row_count=row_count,
                generated_at=now,
            )
            manifest_size = _run_with_retry(
                lambda: atomic_write_json(manifest_path, manifest_payload),
                stage="manifest_write",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"archive_path": str(manifest_path)},
            )
            manifest_digest = sha256_file(manifest_path)
            manifest_artifact = AuditArchiveArtifact(manifest_path, manifest_digest, manifest_size)
            self._metrics.archive_runs_total.labels(status="dry_run", month=month_key).inc()
            return AuditArchiveResult(
                window=window,
                csv=AuditArchiveArtifact(csv_path, "", 0),
                json=AuditArchiveArtifact(json_path, "", 0),
                manifest=manifest_artifact,
                row_count=row_count,
            )

        current_stage = "archive_write"
        try:
            row_count, csv_artifact, json_artifact = _run_with_retry(
                lambda: self._write_artifacts(window, csv_path, json_path),
                stage="archive_write",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"archive_path": str(csv_path.parent)},
            )
            current_stage = "manifest_write"
            manifest_payload = self._build_manifest_payload(
                window,
                csv_artifact=csv_artifact,
                json_artifact=json_artifact,
                manifest_path=manifest_path,
                row_count=row_count,
                generated_at=self._clock.now().astimezone(self._tz),
            )
            manifest_size = _run_with_retry(
                lambda: atomic_write_json(manifest_path, manifest_payload),
                stage="manifest_write",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"archive_path": str(manifest_path)},
            )
            manifest_digest = sha256_file(manifest_path)
            manifest_artifact = AuditArchiveArtifact(manifest_path, manifest_digest, manifest_size)
            result = AuditArchiveResult(
                window=window,
                csv=csv_artifact,
                json=json_artifact,
                manifest=manifest_artifact,
                row_count=row_count,
            )
            current_stage = "release_update"
            _run_with_retry(
                lambda: self._update_release(result),
                stage="release_update",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"archive_path": str(csv_path.parent), "sha256": csv_artifact.sha256},
            )
            current_stage = "partition_metadata"
            _run_with_retry(
                lambda: self._record_partition_metadata(result),
                stage="partition_metadata",
                seed=month_key,
                config=self._config,
                metrics=self._metrics,
                rid=rid,
                op="archive",
                namespace="audit.retention",
                extra={"partition_keys": result.window.month_key},
            )
            self._metrics.archive_runs_total.labels(status="success", month=month_key).inc()
            self._metrics.archive_bytes_total.labels(type="csv").inc(csv_artifact.size_bytes)
            self._metrics.archive_bytes_total.labels(type="json").inc(json_artifact.size_bytes)
            self._metrics.archive_bytes_total.labels(type="manifest").inc(manifest_size)
            return result
        except ArchiveFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            self._metrics.archive_runs_total.labels(status="failure", month=month_key).inc()
            self._metrics.archive_fail_total.labels(stage=current_stage).inc()
            _LOGGER.error(
                "AUDIT_ARCHIVE_FAILURE",
                extra={
                    "rid": rid,
                    "op": "archive",
                    "namespace": "audit.retention",
                    "last_error": repr(exc),
                    "stage": current_stage,
                    "archive_path": str(csv_path.parent),
                    "month": month_key,
                    "sha256": getattr(locals().get("csv_artifact"), "sha256", ""),
                },
            )
            raise ArchiveFailure("AUDIT_ARCHIVE_ERROR: خطا در ایجاد آرشیو ممیزی؛ لطفاً بعداً دوباره تلاش کنید.") from exc

    # ------------------------------------------------------------------
    # Helpers
    def _window(self, month_key: str) -> AuditArchiveWindow:
        if not _MONTH_KEY_RE.match(month_key):
            raise ValueError("CONFIG_VALIDATION_ERROR: پیکربندی ماه نامعتبر است؛ مقادیر نگه‌داری را بررسی کنید.")
        year = int(month_key[:4])
        month = int(month_key[5:7])
        start = datetime(year, month, 1, tzinfo=self._tz)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=self._tz)
        else:
            end = datetime(year, month + 1, 1, tzinfo=self._tz)
        return AuditArchiveWindow(month_key=month_key, start=start, end=end)

    def _artifact_path(self, window: AuditArchiveWindow, *, suffix: str | None = None, name: str | None = None) -> Path:
        year = f"{window.start.year:04d}"
        month = f"{window.start.month:02d}"
        base = self._config.archive_root / "audit" / year / month
        base.mkdir(parents=True, exist_ok=True)
        if name is not None:
            return base / name
        suffix = suffix or ""
        return base / f"audit_{window.month_key}{suffix}"

    def _cleanup_parts(self, window: AuditArchiveWindow) -> None:
        directory = self._artifact_path(window).parent
        for path in directory.glob("*.part"):
            try:
                path.unlink()
            except OSError:
                _LOGGER.warning(
                    "AUDIT_ARCHIVE_CLEANUP_FAILED",
                    extra={"rid": "archive", "path": str(path)},
                )

    def _count_rows(self, window: AuditArchiveWindow) -> int:
        query = text(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE ts >= :start AND ts < :end
            """
        )
        with self._engine.connect() as connection:
            result = connection.execute(query, {"start": window.start, "end": window.end})
            value = result.scalar()
        return int(value or 0)

    @contextmanager
    def _stream_rows(self, window: AuditArchiveWindow) -> Iterator[Iterable[_ArchiveRow]]:
        query = text(
            """
            SELECT id, ts, actor_role, center_scope, action, resource_type, resource_id,
                   job_id, request_id, outcome, error_code, artifact_sha256
            FROM audit_events
            WHERE ts >= :start AND ts < :end
            ORDER BY ts ASC, id ASC
            """
        )
        connection = self._engine.connect()
        result = None
        try:
            result = connection.execution_options(stream_results=True).execute(
                query,
                {"start": window.start, "end": window.end},
            )
            try:
                result = result.yield_per(self._config.fetch_size)
            except AttributeError:
                # Some SQLAlchemy dialects do not support yield_per on Result objects.
                pass

            def iterator() -> Iterator[_ArchiveRow]:
                for row in result:
                    yield self._prepare_row(row._mapping)

            yield iterator()
        finally:
            if result is not None:
                try:
                    result.close()
                except Exception:  # noqa: BLE001
                    pass
            connection.close()

    def _prepare_row(self, mapping: Any) -> _ArchiveRow:
        ts_value = mapping["ts"]
        if isinstance(ts_value, str):
            ts_value = datetime.fromisoformat(ts_value)
        return _ArchiveRow(
            id=int(mapping["id"]),
            ts_iso=self._normalize_iso(ts_value),
            actor_role=str(mapping["actor_role"] or ""),
            center_scope=_sanitize_text(mapping.get("center_scope")),
            action=str(mapping["action"] or ""),
            resource_type=_sanitize_text(mapping.get("resource_type")),
            resource_id=_sanitize_text(mapping.get("resource_id")),
            job_id=_sanitize_text(mapping.get("job_id")),
            request_id=_sanitize_text(mapping.get("request_id")),
            outcome=str(mapping["outcome"] or ""),
            error_code=_sanitize_text(mapping.get("error_code")),
            artifact_sha256=_sanitize_text(mapping.get("artifact_sha256")),
        )

    def _write_artifacts(
        self, window: AuditArchiveWindow, csv_path: Path, json_path: Path
    ) -> tuple[int, AuditArchiveArtifact, AuditArchiveArtifact]:
        row_count = 0
        with self._stream_rows(window) as rows:
            with _atomic_writer(csv_path, mode="w", encoding="utf-8", newline="") as csv_handle, _atomic_writer(
                json_path, mode="w", encoding="utf-8", newline="\r\n"
            ) as json_handle:
                if self._config.csv_bom:
                    csv_handle.write("\ufeff")
                writer = csv.writer(csv_handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
                writer.writerow(
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
                wrote_json = False
                for prepared in rows:
                    writer.writerow(
                        [
                            prepared.ts_iso,
                            prepared.actor_role,
                            prepared.center_scope,
                            prepared.action,
                            prepared.resource_type,
                            prepared.resource_id,
                            prepared.job_id,
                            prepared.request_id,
                            prepared.outcome,
                            prepared.error_code,
                            prepared.artifact_sha256,
                        ]
                    )
                    payload = {
                        "id": prepared.id,
                        "ts": prepared.ts_iso,
                        "actor_role": prepared.actor_role,
                        "center_scope": prepared.center_scope,
                        "action": prepared.action,
                        "resource_type": prepared.resource_type,
                        "resource_id": prepared.resource_id,
                        "job_id": prepared.job_id,
                        "request_id": prepared.request_id,
                        "outcome": prepared.outcome,
                        "error_code": prepared.error_code,
                        "artifact_sha256": prepared.artifact_sha256,
                    }
                    if wrote_json:
                        json_handle.write("\r\n")
                    json_handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    wrote_json = True
                    row_count += 1
        csv_artifact = AuditArchiveArtifact(
            path=csv_path,
            sha256=sha256_file(csv_path),
            size_bytes=csv_path.stat().st_size,
        )
        json_artifact = AuditArchiveArtifact(
            path=json_path,
            sha256=sha256_file(json_path),
            size_bytes=json_path.stat().st_size,
        )
        return row_count, csv_artifact, json_artifact

    def _build_manifest_payload(
        self,
        window: AuditArchiveWindow,
        *,
        csv_artifact: AuditArchiveArtifact,
        json_artifact: AuditArchiveArtifact,
        manifest_path: Path,
        row_count: int,
        generated_at: datetime,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self._config.manifest_schema_version,
            "month": window.month_key,
            "window": {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            },
            "row_count": row_count,
            "generated_at": generated_at.isoformat(),
            "tool": {
                "name": "audit_archiver",
                "version": self._config.tool_version,
            },
            "artifacts": [
                {
                    "name": csv_artifact.path.as_posix(),
                    "sha256": csv_artifact.sha256,
                    "size": csv_artifact.size_bytes,
                    "type": "csv",
                },
                {
                    "name": json_artifact.path.as_posix(),
                    "sha256": json_artifact.sha256,
                    "size": json_artifact.size_bytes,
                    "type": "json",
                },
            ],
        }
        return payload

    def _update_release(self, result: AuditArchiveResult) -> None:
        ts = self._clock.now().astimezone(self._tz)
        for artifact, kind in ((result.csv, "audit-archive-csv"), (result.json, "audit-archive-json")):
            entry = make_manifest_entry(artifact.path, sha256=artifact.sha256, kind=kind, ts=ts)
            self._manifest.update(entry=entry)

    def _record_partition_metadata(self, result: AuditArchiveResult) -> None:
        path = self._config.archive_root / "audit" / "partitions.json"
        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text("utf-8"))
            except json.JSONDecodeError:
                existing = []
        entry = {
            "month": result.window.month_key,
            "start": result.window.start.isoformat(),
            "end": result.window.end.isoformat(),
            "size_bytes": result.csv.size_bytes + result.json.size_bytes + result.manifest.size_bytes,
            "reason": "age",
        }
        existing = [item for item in existing if item.get("month") != result.window.month_key]
        existing.append(entry)
        existing.sort(key=lambda item: item["start"])
        atomic_write_json(path, existing)

    def _normalize_iso(self, value: datetime) -> str:
        if value.tzinfo is None:
            return value.replace(tzinfo=self._tz).astimezone(self._tz).isoformat()
        return value.astimezone(self._tz).isoformat()


@dataclass(slots=True)
class RetentionPlanEntry:
    month_key: str
    reason: str
    start: datetime
    end: datetime
    size_bytes: int


@dataclass(slots=True)
class PartitionInfo:
    month_key: str
    start: datetime
    end: datetime
    size_bytes: int


class AuditRetentionEnforcer:
    """Evaluate partitions and purge only after archive validation."""

    def __init__(
        self,
        *,
        engine: Engine,
        archiver: AuditArchiver,
        metrics: AuditMetrics,
        config: AuditArchiveConfig,
        timezone: ZoneInfo = _PERSIAN_TZ,
    ) -> None:
        self._engine = engine
        self._archiver = archiver
        self._metrics = metrics
        self._config = config
        self._tz = timezone

    def plan(self) -> list[RetentionPlanEntry]:
        partitions = list(self._list_partitions())
        now = self._archiver._clock.now().astimezone(self._tz)
        findings: list[RetentionPlanEntry] = []
        for partition in partitions:
            age_days = (now - partition.start).days
            if self._config.retention_age_days is not None and age_days > self._config.retention_age_days:
                findings.append(
                    RetentionPlanEntry(
                        month_key=partition.month_key,
                        reason="age",
                        start=partition.start,
                        end=partition.end,
                        size_bytes=partition.size_bytes,
                    )
                )
        if self._config.retention_age_months is not None:
            threshold_months = self._config.retention_age_months
            for partition in partitions:
                diff_months = (now.year - partition.start.year) * 12 + (now.month - partition.start.month)
                if diff_months > threshold_months:
                    if not any(item.month_key == partition.month_key for item in findings):
                        findings.append(
                            RetentionPlanEntry(
                                month_key=partition.month_key,
                                reason="age",
                                start=partition.start,
                                end=partition.end,
                                size_bytes=partition.size_bytes,
                            )
                        )
        if self._config.retention_size_bytes is not None:
            total_bytes = sum(item.size_bytes for item in partitions)
            if total_bytes > self._config.retention_size_bytes:
                partitions_sorted = sorted(partitions, key=lambda item: item.start)
                for partition in partitions_sorted:
                    if total_bytes <= self._config.retention_size_bytes:
                        break
                    if not any(item.month_key == partition.month_key for item in findings):
                        findings.append(
                            RetentionPlanEntry(
                                month_key=partition.month_key,
                                reason="size",
                                start=partition.start,
                                end=partition.end,
                                size_bytes=partition.size_bytes,
                            )
                        )
                    total_bytes -= partition.size_bytes
        return sorted(findings, key=lambda item: item.start)

    def enforce(self, *, dry_run: bool = True) -> dict[str, Any]:
        plan = self.plan()
        dry_payload = [self._entry_payload(entry) for entry in plan]
        enforced: list[dict[str, Any]] = []
        if not dry_run:
            for entry in plan:
                rid = f"audit-retention-{entry.month_key}"
                verified = _run_with_retry(
                    lambda: self._verify_archive(entry),
                    stage="retention_verify",
                    seed=entry.month_key,
                    config=self._config,
                    metrics=self._metrics,
                    rid=rid,
                    op="retention",
                    namespace="audit.retention",
                    extra={"partition_keys": entry.month_key},
                )
                if not verified:
                    raise ArchiveFailure("AUDIT_RETENTION_ERROR: پاک‌سازی ناممکن است؛ ابتدا آرشیو معتبر تولید کنید.")
                _run_with_retry(
                    lambda: self._drop_partition(entry),
                    stage="retention_drop",
                    seed=entry.month_key,
                    config=self._config,
                    metrics=self._metrics,
                    rid=rid,
                    op="retention",
                    namespace="audit.retention",
                    extra={"partition_keys": entry.month_key},
                )
                enforced.append(self._entry_payload(entry))
                self._metrics.retention_purges_total.labels(reason=entry.reason).inc()
        report = {"dry_run": dry_payload, "enforced": enforced}
        return report

    def _entry_payload(self, entry: RetentionPlanEntry) -> dict[str, Any]:
        return {
            "month": entry.month_key,
            "reason": entry.reason,
            "start": entry.start.isoformat(),
            "end": entry.end.isoformat(),
            "size_bytes": entry.size_bytes,
        }

    def _verify_archive(self, entry: RetentionPlanEntry) -> bool:
        window = self._archiver._window(entry.month_key)
        manifest_path = self._archiver._artifact_path(window, name="audit_archive_manifest.json")
        if not manifest_path.exists():
            return False
        payload = json.loads(manifest_path.read_text("utf-8"))
        artifacts = {item["type"]: item for item in payload.get("artifacts", []) if "type" in item}
        for kind, artifact in artifacts.items():
            artifact_path = Path(artifact.get("name", ""))
            if not artifact_path.exists():
                return False
            digest = sha256_file(artifact_path)
            if digest != artifact.get("sha256"):
                return False
        return True

    def _drop_partition(self, entry: RetentionPlanEntry) -> None:
        stmt = text(
            "DELETE FROM audit_events WHERE ts >= :start AND ts < :end"
        )
        with self._engine.begin() as connection:
            dialect = connection.dialect.name
            params = {"start": entry.start, "end": entry.end}
            if dialect == "sqlite":
                connection.execute(text("DROP TRIGGER IF EXISTS audit_events_no_update"))
                connection.execute(text("DROP TRIGGER IF EXISTS audit_events_no_delete"))
                connection.execute(stmt, params)
                connection.execute(
                    text(
                        """
                        CREATE TRIGGER audit_events_no_update
                        AFTER UPDATE ON audit_events
                        BEGIN
                            SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
                        END;
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        CREATE TRIGGER audit_events_no_delete
                        AFTER DELETE ON audit_events
                        BEGIN
                            SELECT RAISE(ABORT, 'AUDIT_APPEND_ONLY');
                        END;
                        """
                    )
                )
            else:
                connection.execute(stmt, params)

    def _list_partitions(self) -> Iterator[PartitionInfo]:
        metadata_path = self._archiver._config.archive_root / "audit" / "partitions.json"
        if not metadata_path.exists():
            return
        payload = json.loads(metadata_path.read_text("utf-8"))
        for item in payload:
            month_key = item["month"]
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
            size_bytes = int(item.get("size_bytes", 0))
            yield PartitionInfo(
                month_key=month_key,
                start=start,
                end=end,
                size_bytes=size_bytes,
            )


@contextmanager
def _atomic_writer(path: Path, *, mode: str, encoding: str, newline: str) -> Iterator[Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=path.name, suffix=".part", dir=path.parent)
        with os.fdopen(fd, mode, encoding=encoding, newline=newline) as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:  # noqa: BLE001
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


_DIGIT_MASK_RE = re.compile(r"\d{8,}")


def _mask_digits(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        digest = hashlib.blake2b(match.group(0).encode("utf-8"), digest_size=8).hexdigest()
        return f"masked:{digest}"

    return _DIGIT_MASK_RE.sub(_replace, text)


def _sanitize_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_FA_DIGITS)
    text = text.translate(_PERSIAN_UNIFY)
    text = "".join(ch for ch in text if ch >= " " or ch in {"\t", "\r", "\n"})
    for zw in _ZW_CHARS:
        text = text.replace(zw, "")
    text = text.translate({code: None for code in _CONTROL_ORDS})
    text = text.strip()
    text = _mask_digits(text)
    if text and text[0] in "=+-@":
        text = "'" + text
    return text


def atomic_write_json(path: Path, payload: Any) -> int:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with _atomic_writer(path, mode="w", encoding="utf-8", newline="") as handle:
        handle.write(data)
    return path.stat().st_size


__all__ = [
    "AuditArchiveConfig",
    "AuditArchiver",
    "AuditArchiveResult",
    "AuditArchiveArtifact",
    "AuditArchiveWindow",
    "AuditRetentionEnforcer",
    "RetentionPlanEntry",
    "PartitionInfo",
    "ArchiveFailure",
]
