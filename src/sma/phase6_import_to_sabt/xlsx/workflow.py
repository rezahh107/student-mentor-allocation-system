from __future__ import annotations

import csv
import itertools
import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Iterable, Optional
import sma.core.clock as core_clock

from sma.phase6_import_to_sabt.sanitization import sanitize_text
from sma.phase6_import_to_sabt.models import SignedURLProvider
from sma.phase6_import_to_sabt.security.signer import DualKeySigner, SigningKeySet
from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition
from sma.phase6_import_to_sabt.xlsx.constants import DEFAULT_CHUNK_SIZE, SENSITIVE_COLUMNS
from sma.phase6_import_to_sabt.xlsx.job_store import ExportJobStore, InMemoryExportJobStore
from sma.phase6_import_to_sabt.xlsx.metrics import ImportExportMetrics
from sma.phase6_import_to_sabt.xlsx.reader import XLSXUploadReader
from sma.phase6_import_to_sabt.xlsx.utils import atomic_write, cleanup_partials, sha256_file, write_manifest
from sma.phase6_import_to_sabt.xlsx.writer import EXPORT_COLUMNS, XLSXStreamWriter

logger = logging.getLogger(__name__)

ExportDataProvider = Callable[[int, Optional[int]], Iterable[dict[str, object]]]


@dataclass(slots=True)
class UploadRecord:
    id: str
    status: str
    format: str
    manifest_path: Path
    manifest: dict[str, object]


@dataclass(slots=True)
class ExportRecord:
    id: str
    status: str
    format: str
    artifact_path: Path
    manifest_path: Path
    manifest: dict[str, object]
    files: list[dict[str, object]]
    metadata: dict[str, object]


class ImportToSabtWorkflow:
    def __init__(
        self,
        *,
        storage_dir: Path,
        clock,
        metrics: ImportExportMetrics,
        data_provider,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        job_store: ExportJobStore | None = None,
        sleeper: Callable[[float], None] | None = None,
        signed_url_secret: str = "import-to-sabt-secret",
        signed_url_kid: str = "local",
        signed_url_provider: SignedURLProvider | None = None,
        signed_url_ttl_seconds: int = 900,
    ) -> None:
        self.storage_dir = storage_dir
        self.clock = clock
        self.metrics = metrics
        self.data_provider = data_provider
        self.chunk_size = chunk_size
        self._upload_reader = XLSXUploadReader()
        self._xlsx_writer = XLSXStreamWriter(chunk_size=chunk_size)
        self._timezone = core_clock.validate_timezone("Asia/Tehran")
        self._counter = itertools.count(1)
        self._lock = threading.Lock()
        self._uploads: dict[str, UploadRecord] = {}
        self._exports: dict[str, ExportRecord] = {}
        self._sleeper = sleeper
        if signed_url_provider is None:
            signing_keys = SigningKeySet([SigningKeyDefinition(signed_url_kid, signed_url_secret, "active")])
            signed_url_provider = DualKeySigner(
                keys=signing_keys,
                clock=self.clock,
                metrics=metrics,
                default_ttl_seconds=signed_url_ttl_seconds,
            )
        self._signed_urls = signed_url_provider
        self._signed_url_ttl = signed_url_ttl_seconds
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        cleanup_partials(self.storage_dir)
        self.job_store: ExportJobStore = job_store or InMemoryExportJobStore(
            now=self._now_iso,
            metrics=metrics,
        )

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            counter = next(self._counter)
        deterministic = uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{counter}")
        return f"{prefix}-{deterministic.hex[:12]}"

    def _now(self):
        current = self.clock.now()
        if current.tzinfo is None:
            return current.replace(tzinfo=self._timezone)
        return current.astimezone(self._timezone)

    def _now_iso(self) -> str:
        return self._now().isoformat()

    def create_upload(self, *, profile: str, year: int, file_path: Path) -> UploadRecord:
        upload_id = self._next_id("upload")
        logger.info("upload.start", extra={"upload_id": upload_id})
        result = self._upload_reader.read(file_path)
        sha256 = sha256_file(file_path)
        manifest_payload = {
            "id": upload_id,
            "format": result.format,
            "profile": sanitize_text(profile),
            "filters": {"year": year},
            "excel_safety": result.excel_safety,
            "generated_at": self._now_iso(),
            "sha256": sha256,
            "row_counts": result.row_counts,
            "snapshot": {"type": "upload"},
        }
        manifest_path = self.storage_dir / f"{upload_id}_manifest.json"
        write_manifest(manifest_path, manifest_payload)
        self.metrics.upload_jobs_total.labels(status="success", format=result.format).inc()
        self.metrics.upload_rows_total.labels(format=result.format).inc(len(result.rows))
        logger.info(
            "upload.finish",
            extra={"upload_id": upload_id, "rows": len(result.rows), "format": result.format},
        )
        record = UploadRecord(
            id=upload_id,
            status="SUCCESS",
            format=result.format,
            manifest_path=manifest_path,
            manifest=manifest_payload,
        )
        self._uploads.setdefault(upload_id, record)
        return record

    def create_export(self, *, year: int, center: int | None = None, file_format: str = "xlsx") -> ExportRecord:
        normalized_format = sanitize_text(file_format or "xlsx").lower() or "xlsx"
        export_id = self._next_id("export")
        logger.info("export.start", extra={"export_id": export_id, "format": normalized_format})
        filters = {"year": year, "center": center}
        self.job_store.begin(export_id, file_format=normalized_format, filters=filters)
        try:
            rows = list(self.data_provider(year, center))
            if not rows:
                raise ValueError("درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.")
            prepare_start = perf_counter()
            normalized_rows = [self._xlsx_writer.prepare_row(row) for row in rows]
            prepare_duration = perf_counter() - prepare_start
            self.metrics.export_duration_seconds.labels(phase="prepare", format=normalized_format).observe(prepare_duration)
            row_counts_cache: dict[str, dict[str, int]] = {}
            write_start = perf_counter()
            artifact_path = self._write_artifact(
                export_id,
                normalized_rows,
                normalized_format,
                row_counts_cache,
            )
            write_duration = perf_counter() - write_start
            self.metrics.export_duration_seconds.labels(phase="write", format=normalized_format).observe(write_duration)
            sha256 = sha256_file(artifact_path)
            manifest_path = self.storage_dir / f"{export_id}_manifest.json"
            manifest_payload = {
                "id": export_id,
                "format": normalized_format,
                "generated_at": self._now_iso(),
                "filters": filters,
                "excel_safety": {
                    "normalized": True,
                    "formula_guard": True,
                    "sensitive_text": list(SENSITIVE_COLUMNS),
                },
                "snapshot": {"type": "full"},
                "files": [
                    {
                        "name": artifact_path.name,
                        "sha256": sha256,
                        "row_counts": row_counts_cache[artifact_path.name],
                    }
                ],
            }
            write_manifest(manifest_path, manifest_payload)
            files_metadata = self._build_file_metadata(artifact_path.name, sha256, row_counts_cache[artifact_path.name])
            job_payload = self.job_store.complete(
                export_id,
                artifact_path=str(artifact_path),
                manifest_path=str(manifest_path),
                files=files_metadata,
                excel_safety=manifest_payload["excel_safety"],
                manifest=manifest_payload,
            )
            self.metrics.export_jobs_total.labels(status="success", format=normalized_format).inc()
            total_rows = sum(row_counts_cache[artifact_path.name].values())
            self.metrics.export_rows_total.labels(format=normalized_format).inc(total_rows)
            self.metrics.export_file_bytes_total.labels(format=normalized_format).inc(artifact_path.stat().st_size)
            logger.info(
                "export.finish",
                extra={
                    "export_id": export_id,
                    "rows": total_rows,
                    "format": normalized_format,
                    "rid": export_id,
                    "namespace": filters,
                },
            )
            record = ExportRecord(
                id=export_id,
                status="SUCCESS",
                format=normalized_format,
                artifact_path=artifact_path,
                manifest_path=manifest_path,
                manifest=manifest_payload,
                files=manifest_payload["files"],
                metadata=job_payload,
            )
            self._exports.setdefault(export_id, record)
            return record
        except ValueError as exc:
            error_payload = {
                "code": "EXPORT_VALIDATION_ERROR",
                "message": "درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.",
            }
            self.metrics.export_jobs_total.labels(status="failure", format=normalized_format).inc()
            self.job_store.fail(export_id, error=error_payload)
            logger.error(
                "export.validation_failed",
                extra={
                    "export_id": export_id,
                    "format": normalized_format,
                    "rid": export_id,
                    "last_error": str(exc),
                },
            )
            raise ValueError(error_payload["message"]) from exc
        except Exception as exc:  # noqa: PERF203 deliberate broad catch for deterministic error handling
            error_payload = {
                "code": "EXPORT_IO_ERROR",
                "message": "خطا در تولید فایل XLSX؛ لطفاً دوباره تلاش کنید.",
            }
            self.metrics.export_jobs_total.labels(status="failure", format=normalized_format).inc()
            self.job_store.fail(export_id, error=error_payload)
            logger.exception(
                "export.io_failed",
                extra={
                    "export_id": export_id,
                    "format": normalized_format,
                    "rid": export_id,
                    "last_error": str(exc),
                },
            )
            raise RuntimeError(error_payload["message"]) from exc

    def _write_artifact(
        self,
        export_id: str,
        rows: list[dict[str, str]],
        file_format: str,
        row_counts_cache: dict[str, dict[str, int]],
    ) -> Path:
        if file_format == "xlsx":
            path = self.storage_dir / f"{export_id}.xlsx"

            def on_retry(attempt: int) -> None:
                logger.warning(
                    "export.retry",
                    extra={
                        "export_id": export_id,
                        "attempt": attempt,
                        "operation": "xlsx_fsync",
                    },
                )

            artifact = self._xlsx_writer.write(
                rows,
                path,
                on_retry=on_retry,
                metrics=self.metrics,
                format_label="xlsx",
                sleeper=self._sleeper,
            )
            row_counts_cache[path.name] = artifact.row_counts
            return artifact.path
        if file_format == "csv":
            path = self.storage_dir / f"{export_id}.csv"
            self._write_csv(rows, path)
            counts = {"Sheet_001": len(rows)}
            row_counts_cache[path.name] = counts
            return path
        raise ValueError("EXPORT_FORMAT_UNSUPPORTED")

    def _write_csv(self, rows: list[dict[str, str]], path: Path) -> None:
        def on_retry(attempt: int) -> None:
            logger.warning(
                "export.retry",
                extra={"export_id": path.stem, "attempt": attempt, "operation": "csv_fsync"},
            )

        with atomic_write(
            path,
            mode="w",
            backoff_seed="csv",
            on_retry=on_retry,
            metrics=self.metrics,
            format_label="csv",
            sleeper=self._sleeper,
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(EXPORT_COLUMNS), lineterminator="\r\n", quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        return self._uploads.get(upload_id)

    def activate_upload(self, upload_id: str) -> UploadRecord:
        record = self._uploads.get(upload_id)
        if record is None:
            raise KeyError(upload_id)
        record.status = "ACTIVATED"
        record.manifest["activated_at"] = self._now().isoformat()
        write_manifest(record.manifest_path, record.manifest)  # type: ignore[arg-type]
        return record

    def _build_file_metadata(self, name: str, sha256: str, rows: dict[str, int]) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for sheet, count in rows.items():
            entries.append({"path": name, "sheet": sheet, "rows": count, "sha256": sha256})
        return entries

    def build_signed_urls(self, record: ExportRecord) -> list[dict[str, str]]:
        urls: list[dict[str, str]] = []
        files = record.manifest.get("files", [])
        for file_info in files:
            name = file_info.get("name") or file_info.get("path")
            if not name:
                continue
            artifact_path = record.artifact_path
            if artifact_path.is_absolute():
                candidate = artifact_path
            else:
                candidate = (self.storage_dir / artifact_path).resolve()
            try:
                relative = candidate.relative_to(self.storage_dir)
            except ValueError:
                relative = Path(name)
            signed_url = self._signed_urls.sign(str(relative), expires_in=self._signed_url_ttl)
            urls.append({"name": name, "url": signed_url})
        return urls

    def get_export(self, export_id: str) -> ExportRecord | None:
        cached = self._exports.get(export_id)
        if cached is not None:
            return cached
        payload = self.job_store.load(export_id)
        if not payload:
            return None
        manifest = payload.get("manifest") or {}
        artifact_path_str = payload.get("artifact_path") or ""
        manifest_path_str = payload.get("manifest_path") or self.storage_dir / f"{export_id}_manifest.json"
        artifact_path = Path(artifact_path_str) if artifact_path_str else self.storage_dir / f"{export_id}.{payload.get('format', 'xlsx')}"
        manifest_path = Path(manifest_path_str) if isinstance(manifest_path_str, str) else manifest_path_str
        record = ExportRecord(
            id=payload.get("id", export_id),
            status=payload.get("status", "UNKNOWN"),
            format=payload.get("format", "xlsx"),
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            manifest=manifest,
            files=manifest.get("files", []),
            metadata=payload,
        )
        self._exports[export_id] = record
        return record


__all__ = ["ImportToSabtWorkflow", "UploadRecord", "ExportRecord"]
