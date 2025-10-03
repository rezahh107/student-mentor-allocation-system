from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from core.clock import Clock as CoreClock, tehran_clock
from core.retry import RetryPolicy, build_sync_clock_sleeper, execute_with_retry
from phase6_import_to_sabt.models import (
    COUNTER_PREFIX,
    ExportExecutionStats,
    ExportFilters,
    ExportManifest,
    ExportManifestFile,
    ExportOptions,
    ExportProfile,
    ExportSnapshot,
    ExporterDataSource,
    NormalizedStudentRow,
    SABT_V1_PROFILE,
    SpecialSchoolsRoster,
)
from phase6_import_to_sabt.export_writer import (
    EXPORT_COLUMNS,
    ExportWriter,
    atomic_writer,
)
from phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text
from shared.counter_rules import validate_counter

PHONE_RE = re.compile(r"^09\d{9}$")
RETRYABLE_EXPORT_ERRORS: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, OSError)
SORT_KEYS: tuple[str, ...] = (
    "year_code",
    "reg_center",
    "group_code",
    "school_code",
    "national_id",
)


class ExportValidationError(ValueError):
    pass


class ExportIOError(RuntimeError):
    """Raised when IO operations fail during export finalization."""

    def __init__(self, message: str = "EXPORT_IO_ERROR") -> None:
        super().__init__(message)


class ImportToSabtExporter:
    def __init__(
        self,
        *,
        data_source: ExporterDataSource,
        roster: SpecialSchoolsRoster,
        output_dir: Path,
        profile: ExportProfile = SABT_V1_PROFILE,
        duration_clock: Callable[[], float] | None = None,
        clock: CoreClock | None = None,
        retry_policy: RetryPolicy | None = None,
        retryable_exceptions: Iterable[type[Exception]] | None = None,
        operation_namespace: str = "import_to_sabt.exporter",
    ) -> None:
        self.data_source = data_source
        self.roster = roster
        self.output_dir = output_dir
        self.profile = profile
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._duration_clock = duration_clock or time.perf_counter
        self._last_stats: ExportExecutionStats | None = None
        self._clock = clock or tehran_clock()
        self._retry_policy = retry_policy or RetryPolicy()
        self._retryable_exceptions = tuple(retryable_exceptions or RETRYABLE_EXPORT_ERRORS)
        self._sleeper = build_sync_clock_sleeper(self._clock)
        self._operation_namespace = operation_namespace
        self._cleanup_partials()

    def _cleanup_partials(self) -> None:
        for partial in self.output_dir.glob("*.part"):
            try:
                partial.unlink()
            except FileNotFoundError:
                continue

    def _remove_manifest(self) -> None:
        manifest_path = self.output_dir / "export_manifest.json"
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except FileNotFoundError:  # pragma: no cover - race resistant cleanup
                pass

    def run(
        self,
        *,
        filters: ExportFilters,
        options: ExportOptions,
        snapshot: ExportSnapshot,
        clock_now: datetime,
        stats: ExportExecutionStats | None = None,
        correlation_id: str = "import_to_sabt_export",
    ) -> ExportManifest:
        if options.chunk_size <= 0:
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:chunk_size")
        stats = stats or ExportExecutionStats()
        self._cleanup_partials()
        self._remove_manifest()

        def _query_phase() -> list[dict[str, str]]:
            with self._measure_phase(stats, "query"):
                rows = list(self.data_source.fetch_rows(filters, snapshot))
                if not rows:
                    raise ExportValidationError("EXPORT_EMPTY")
                normalized_rows = [self._normalize_row(row, filters) for row in rows]
                return self._sort_rows(normalized_rows)

        sorted_rows = execute_with_retry(
            _query_phase,
            policy=self._retry_policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=self._retryable_exceptions,
            correlation_id=correlation_id,
            op=f"{self._operation_namespace}.query",
        )
        timestamp = clock_now.strftime("%Y%m%d%H%M%S")
        format_label = options.output_format

        def _write_phase() -> tuple[list[ExportManifestFile], int, dict[str, Any]]:
            self._cleanup_partials()
            return self._write_exports(
                filters=filters,
                rows=sorted_rows,
                options=options,
                timestamp=timestamp,
                stats=stats,
            )

        files, total_rows, excel_safety = execute_with_retry(
            _write_phase,
            policy=self._retry_policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=self._retryable_exceptions,
            correlation_id=correlation_id,
            op=f"{self._operation_namespace}.write",
        )

        config_flags = {
            "format": format_label,
            "csv_bom": bool(options.include_bom) if format_label == "csv" else False,
            "crlf": options.newline == "\r\n",
        }

        manifest = ExportManifest(
            profile=self.profile,
            filters=filters,
            snapshot=snapshot,
            generated_at=clock_now,
            total_rows=total_rows,
            files=tuple(files),
            delta_window=filters.delta,
            metadata={
                "timestamp": timestamp,
                "files_order": [file.name for file in files],
                "chunk_size": options.chunk_size,
                "sort_keys": list(SORT_KEYS),
                "config": config_flags,
            },
            format=format_label,
            excel_safety=excel_safety,
        )
        manifest_path = self.output_dir / "export_manifest.json"
        filters_payload: dict[str, object] = {"year": filters.year, "center": filters.center}
        if filters.delta:
            filters_payload["delta"] = {
                "created_at_watermark": filters.delta.created_at_watermark.isoformat(),
                "id_watermark": filters.delta.id_watermark,
            }
        payload = {
            "profile": self.profile.full_name,
            "filters": filters_payload,
            "snapshot": {
                "marker": snapshot.marker,
                "created_at": snapshot.created_at.isoformat(),
            },
            "generated_at": clock_now.isoformat(),
            "total_rows": total_rows,
            "files": [
                {
                    **asdict(file),
                    "sheets": [list(item) for item in file.sheets] if file.sheets else [],
                }
                for file in files
            ],
            "metadata": manifest.metadata,
            "format": format_label,
            "excel_safety": excel_safety,
            "config": config_flags,
        }
        if filters.delta:
            payload["delta_window"] = {
                "created_at_watermark": filters.delta.created_at_watermark.isoformat(),
                "id_watermark": filters.delta.id_watermark,
            }

        def _finalize_phase() -> None:
            with self._measure_phase(stats, "finalize"):
                with atomic_writer(manifest_path) as fh:
                    json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

        execute_with_retry(
            _finalize_phase,
            policy=self._retry_policy,
            clock=self._clock,
            sleeper=self._sleeper,
            retryable=self._retryable_exceptions,
            correlation_id=correlation_id,
            op=f"{self._operation_namespace}.finalize",
        )
        self._last_stats = stats
        return manifest

    def _create_writer(self, options: ExportOptions) -> ExportWriter:
        return ExportWriter(
            columns=EXPORT_COLUMNS,
            sensitive_columns=self.profile.sensitive_columns,
            newline=options.newline,
            include_bom=options.include_bom,
            chunk_size=options.chunk_size,
            formula_guard=bool(options.excel_mode),
        )

    def _write_exports(
        self,
        *,
        filters: ExportFilters,
        rows: Sequence[dict[str, str]],
        options: ExportOptions,
        timestamp: str,
        stats: ExportExecutionStats,
    ) -> tuple[list[ExportManifestFile], int, dict[str, Any]]:
        writer = self._create_writer(options)
        format_label = options.output_format

        if format_label == "csv":
            result = writer.write_csv(
                rows,
                path_factory=lambda index: self.output_dir
                / self._build_filename(filters, timestamp, index, extension="csv"),
            )
        else:
            result = writer.write_xlsx(
                rows,
                path_factory=lambda index: self.output_dir
                / self._build_filename(filters, timestamp, index, extension="xlsx"),
            )

        files = [
            ExportManifestFile(
                name=file.name,
                sha256=file.sha256,
                row_count=file.row_count,
                byte_size=file.byte_size,
                sheets=file.sheets,
            )
            for file in result.files
        ]
        return files, result.total_rows, result.excel_safety

    def _measure_phase(self, stats: ExportExecutionStats, phase: str):
        @contextmanager
        def _ctx() -> Iterator[None]:
            start = self._duration_clock()
            try:
                yield
            finally:
                elapsed = self._duration_clock() - start
                stats.add_duration(phase, elapsed)

        return _ctx()

    @property
    def last_stats(self) -> ExportExecutionStats | None:
        return self._last_stats

    def _normalize_row(self, row: NormalizedStudentRow, filters: ExportFilters) -> dict[str, str]:
        school_code = row.school_code
        derived_student_type = 1 if self.roster.is_special(filters.year, school_code) else 0
        reg_center = int(row.reg_center)
        reg_status = int(row.reg_status)
        if reg_center not in {0, 1, 2}:
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:reg_center")
        if reg_status not in {0, 1, 3}:
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:reg_status")
        mobile = sanitize_phone(row.mobile)
        if not PHONE_RE.match(mobile):
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:mobile")
        counter = validate_counter(sanitize_text(row.counter))
        gender = int(row.gender)
        expected_prefix = COUNTER_PREFIX.get(gender)
        if expected_prefix is None or expected_prefix not in counter:
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:counter_prefix")
        record = {
            "national_id": sanitize_text(row.national_id),
            "counter": counter,
            "first_name": sanitize_text(row.first_name),
            "last_name": sanitize_text(row.last_name),
            "gender": str(gender),
            "mobile": mobile,
            "reg_center": str(reg_center),
            "reg_status": str(reg_status),
            "group_code": str(row.group_code),
            "student_type": str(derived_student_type),
            "school_code": "" if school_code is None else f"{school_code:06d}",
            "mentor_id": sanitize_text(row.mentor_id or ""),
            "mentor_name": sanitize_text(row.mentor_name or ""),
            "mentor_mobile": sanitize_phone(row.mentor_mobile or ""),
            "allocation_date": row.allocation_date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "year_code": sanitize_text(row.year_code),
        }
        return record

    def _sort_rows(self, rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
        def _int_key(value: str | None, default: int = 0) -> int:
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        def _school_key(value: str | None) -> int:
            return _int_key(value, default=999_999)

        return sorted(
            rows,
            key=lambda r: (
                str(r["year_code"]),
                _int_key(r.get("reg_center")),
                _int_key(r.get("group_code")),
                _school_key(r.get("school_code")),
                r["national_id"],
            ),
        )

    def _build_filename(self, filters: ExportFilters, timestamp: str, seq: int, *, extension: str) -> str:
        center_part = str(filters.center) if filters.center is not None else "ALL"
        return f"export_{self.profile.full_name}_{filters.year}-{center_part}_{timestamp}_{seq:03d}.{extension}"

