from __future__ import annotations

from collections.abc import Iterable
from typing import Iterable, List

from sma.phase6_import_to_sabt.models import ExportFilters, ExportSnapshot, ExporterDataSource, NormalizedStudentRow


class InMemoryDataSource(ExporterDataSource):
    def __init__(self, rows: Iterable[NormalizedStudentRow]):
        self.rows: List[NormalizedStudentRow] = list(rows)

    def fetch_rows(self, filters: ExportFilters, snapshot: ExportSnapshot) -> Iterable[NormalizedStudentRow]:
        for row in self.rows:
            if row.year_code != str(filters.year):
                continue
            if filters.center is not None and row.reg_center != filters.center:
                continue
            if filters.delta:
                if row.created_at < filters.delta.created_at_watermark:
                    continue
                if row.created_at == filters.delta.created_at_watermark and row.id <= filters.delta.id_watermark:
                    continue
            yield row
