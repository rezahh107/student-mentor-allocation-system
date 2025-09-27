from __future__ import annotations

import csv
import hashlib
import os
import re
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .models import (
    COUNTER_PREFIX,
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
from .sanitization import guard_formula, sanitize_phone, sanitize_text

PHONE_RE = re.compile(r"^09\d{9}$")
COUNTER_RE = re.compile(r"^\d{2}(357|373)\d{4}$")


class ExportValidationError(ValueError):
    pass


class ImportToSabtExporter:
    def __init__(
        self,
        *,
        data_source: ExporterDataSource,
        roster: SpecialSchoolsRoster,
        output_dir: Path,
        profile: ExportProfile = SABT_V1_PROFILE,
    ) -> None:
        self.data_source = data_source
        self.roster = roster
        self.output_dir = output_dir
        self.profile = profile
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_partials()

    def _cleanup_partials(self) -> None:
        for partial in self.output_dir.glob("*.part"):
            try:
                partial.unlink()
            except FileNotFoundError:
                continue

    def run(
        self,
        *,
        filters: ExportFilters,
        options: ExportOptions,
        snapshot: ExportSnapshot,
        clock_now: datetime,
    ) -> ExportManifest:
        if options.chunk_size <= 0:
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:chunk_size")
        rows = list(self.data_source.fetch_rows(filters, snapshot))
        if not rows:
            raise ExportValidationError("EXPORT_EMPTY")
        normalized_rows = [self._normalize_row(row, filters) for row in rows]
        sorted_rows = self._sort_rows(normalized_rows)
        timestamp = clock_now.strftime("%Y%m%d%H%M%S")
        files: list[ExportManifestFile] = []
        total_rows = 0
        for index, chunk in enumerate(_chunk(sorted_rows, options.chunk_size), start=1):
            filename = self._build_filename(filters, timestamp, index)
            path = self.output_dir / filename
            byte_size = self._write_chunk(path, chunk, options)
            sha256 = _sha256_file(path)
            files.append(
                ExportManifestFile(
                    name=filename,
                    sha256=sha256,
                    row_count=len(chunk),
                    byte_size=byte_size,
                )
            )
            total_rows += len(chunk)
        manifest = ExportManifest(
            profile=self.profile,
            filters=filters,
            snapshot=snapshot,
            generated_at=clock_now,
            total_rows=total_rows,
            files=tuple(files),
            delta_window=filters.delta,
            metadata={"timestamp": timestamp},
        )
        manifest_path = self.output_dir / f"manifest_{self.profile.full_name}_{timestamp}.json"
        with atomic_writer(manifest_path) as fh:
            import json

            filters_payload: dict[str, object] = {"year": filters.year, "center": filters.center}
            if filters.delta:
                filters_payload["delta"] = {
                    "created_at_watermark": filters.delta.created_at_watermark.isoformat(),
                    "id_watermark": filters.delta.id_watermark,
                }
            payload = {
                "profile": self.profile.full_name,
                "filters": filters_payload,
                "snapshot": {"marker": snapshot.marker, "created_at": snapshot.created_at.isoformat()},
                "generated_at": clock_now.isoformat(),
                "total_rows": total_rows,
                "files": [asdict(file) for file in files],
                "metadata": manifest.metadata,
            }
            if filters.delta:
                payload["delta_window"] = {
                    "created_at_watermark": filters.delta.created_at_watermark.isoformat(),
                    "id_watermark": filters.delta.id_watermark,
                }
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return manifest

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
        counter = sanitize_text(row.counter)
        if not COUNTER_RE.match(counter):
            raise ExportValidationError("EXPORT_VALIDATION_ERROR:counter")
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
        return sorted(
            rows,
            key=lambda r: (
                r["year_code"],
                r["reg_center"],
                r["group_code"],
                r["school_code"] or "999999",
                r["national_id"],
            ),
        )

    def _build_filename(self, filters: ExportFilters, timestamp: str, seq: int) -> str:
        center_part = str(filters.center) if filters.center is not None else "ALL"
        return f"export_{self.profile.full_name}_{filters.year}-{center_part}_{timestamp}_{seq:03d}.csv"

    def _write_chunk(
        self,
        path: Path,
        rows: Sequence[dict[str, str]],
        options: ExportOptions,
    ) -> int:
        newline = options.newline
        encoding = "utf-8-sig" if options.include_bom else "utf-8"
        columns = [
            "national_id",
            "counter",
            "first_name",
            "last_name",
            "gender",
            "mobile",
            "reg_center",
            "reg_status",
            "group_code",
            "student_type",
            "school_code",
            "mentor_id",
            "mentor_name",
            "mentor_mobile",
            "allocation_date",
            "year_code",
        ]
        total_bytes = 0
        with atomic_writer(path, newline="", encoding=encoding) as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=columns,
                quoting=csv.QUOTE_ALL,
                lineterminator=newline,
            )
            writer.writeheader()
            for row in rows:
                prepared = dict(row)
                if options.excel_mode:
                    for column in self.profile.excel_risky_columns:
                        prepared[column] = guard_formula(prepared[column])
                writer.writerow(prepared)
        total_bytes = path.stat().st_size
        return total_bytes


def _chunk(rows: Sequence[dict[str, str]], size: int) -> Iterator[Sequence[dict[str, str]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


@contextmanager
def atomic_writer(path: Path, newline: str = "\n", encoding: str = "utf-8"):
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "w", encoding=encoding, newline=newline) as fh:
        try:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        except Exception:
            fh.close()
            if temp_path.exists():
                temp_path.unlink()
            raise
    os.replace(temp_path, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
