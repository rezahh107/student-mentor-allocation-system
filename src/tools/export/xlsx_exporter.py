"""XLSX exporter for allocation data using openpyxl."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - import guard for optional dependency
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Alignment
except ImportError as exc:  # pragma: no cover - handled in tests
    raise ImportError("برای خروجی XLSX باید openpyxl نصب شود") from exc
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.persistence.models import AllocationRecord

_HEADERS = (
    "شناسه تخصیص",
    "کد تخصیص",
    "کد سال",
    "کد ملی دانش‌آموز",
    "شناسه منتور",
    "وضعیت",
    "کد سیاست",
    "زمان ایجاد",
)
_SENSITIVE_PREFIXES = ("=", "+", "-", "@")


@dataclass(slots=True)
class XLSXAllocationExporter:
    """Stream allocations into an XLSX workbook."""

    chunk_size: int = 1000
    excel_safe: bool = True

    def export(self, *, session: Session, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet(title="Allocations")
        sheet.sheet_view.rightToLeft = True
        header_row = []
        for title in _HEADERS:
            cell = WriteOnlyCell(sheet, value=title)
            cell.alignment = Alignment(horizontal="center")
            header_row.append(cell)
        sheet.append(header_row)

        for row in self._stream_rows(session=session):
            values = [self._prepare(value) for value in row]
            cells = []
            for value in values:
                cell = WriteOnlyCell(sheet, value=value)
                cell.alignment = Alignment(horizontal="right")
                cells.append(cell)
            sheet.append(cells)

        workbook.save(output)
        return output

    def _stream_rows(self, *, session: Session):
        stmt = select(AllocationRecord).order_by(AllocationRecord.allocation_id)
        stream = session.execute(stmt).yield_per(self.chunk_size)
        for (record,) in stream:
            yield (
                record.allocation_id,
                record.allocation_code,
                record.year_code,
                record.student_id,
                record.mentor_id,
                record.status,
                record.policy_code or "",
                record.created_at.isoformat() if record.created_at else "",
            )

    def _prepare(self, value: object) -> object:
        if value is None:
            return ""
        text = str(value)
        if self.excel_safe and isinstance(text, str) and text.startswith(_SENSITIVE_PREFIXES):
            return "'" + text
        return text


def export_allocations_to_xlsx(
    *,
    session: Session,
    output: Path,
    chunk_size: int = 1000,
    excel_safe: bool = True,
) -> Path:
    exporter = XLSXAllocationExporter(chunk_size=chunk_size, excel_safe=excel_safe)
    return exporter.export(session=session, output=output)
