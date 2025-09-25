"""Streaming CSV exporter for allocation data."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.persistence.models import AllocationRecord

_SENSITIVE_PREFIXES = ("=", "+", "-", "@")
_DEFAULT_HEADERS: Sequence[tuple[str, str]] = (
    ("allocation_id", "شناسه تخصیص"),
    ("allocation_code", "کد تخصیص"),
    ("year_code", "کد سال"),
    ("student_id", "کد ملی دانش‌آموز"),
    ("mentor_id", "شناسه منتور"),
    ("status", "وضعیت"),
    ("policy_code", "کد سیاست"),
    ("created_at", "زمان ایجاد"),
)


@dataclass(slots=True)
class CSVAllocationExporter:
    """Export allocations to CSV with Excel-friendly options."""

    bom: bool = False
    crlf: bool = False
    chunk_size: int = 1000
    excel_safe: bool = True

    def export(self, *, session: Session, output: Path) -> Path:
        """Stream allocations to the provided CSV path."""

        output.parent.mkdir(parents=True, exist_ok=True)
        newline = "\r\n" if self.crlf else "\n"
        with output.open("w", encoding="utf-8", newline="") as handle:
            if self.bom:
                handle.write("\ufeff")
            writer = csv.writer(
                handle,
                delimiter=",",
                quoting=csv.QUOTE_ALL,
                lineterminator=newline,
            )
            writer.writerow([header for _, header in _DEFAULT_HEADERS])
            buffer: list[list[str]] = []
            for row in self._stream_rows(session=session):
                buffer.append([self._prepare_value(row[key]) for key, _ in _DEFAULT_HEADERS])
                if len(buffer) >= self.chunk_size:
                    writer.writerows(buffer)
                    handle.flush()
                    buffer.clear()
            if buffer:
                writer.writerows(buffer)
        return output

    def _prepare_value(self, value: object) -> str:
        if value is None:
            return ""
        text = str(value)
        if self.excel_safe and text.startswith(_SENSITIVE_PREFIXES):
            return "'" + text
        return text

    def _stream_rows(self, *, session: Session) -> Iterator[dict[str, object]]:
        stmt = select(AllocationRecord).order_by(AllocationRecord.allocation_id)
        stream = session.execute(stmt).yield_per(self.chunk_size)
        for (record,) in stream:
            yield {
                "allocation_id": record.allocation_id,
                "allocation_code": record.allocation_code,
                "year_code": record.year_code,
                "student_id": record.student_id,
                "mentor_id": record.mentor_id,
                "status": record.status,
                "policy_code": record.policy_code or "",
                "created_at": record.created_at.isoformat() if record.created_at else "",
            }


def export_allocations_to_csv(
    *,
    session: Session,
    output: Path,
    bom: bool = False,
    crlf: bool = False,
    chunk_size: int = 1000,
    excel_safe: bool = True,
) -> Path:
    """Convenience function to export allocations using default columns."""

    exporter = CSVAllocationExporter(bom=bom, crlf=crlf, chunk_size=chunk_size, excel_safe=excel_safe)
    return exporter.export(session=session, output=output)
