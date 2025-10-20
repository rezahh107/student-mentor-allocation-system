from __future__ import annotations

import asyncio
from typing import List

from sma.services.excel_service import ExcelExportService
from sma.api.mock_data import MockBackend


async def _collect_progress(done_list: List[int], d: int, t: int):
    done_list.append(d)
    return True


def test_excel_export_progress_callbacks(tmp_path):
    svc = ExcelExportService()
    backend = MockBackend()
    students = backend._students[:100]
    out = tmp_path / "export.xlsx"
    done_list: List[int] = []

    async def run():
        await svc.export_students(students, str(out), progress_callback=lambda d, t: _collect_progress(done_list, d, t))

    asyncio.run(run())
    assert out.exists()
    # At least some progress reported
    assert len(done_list) > 0

