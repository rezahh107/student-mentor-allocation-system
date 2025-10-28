"""تست‌های هدفمند برای ایمنی خروجی‌های اکسل فارسی."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from sqlalchemy import text

from sma.phase6_import_to_sabt.export_writer import ExportWriter

from tests.conftest import retry


def _نمونه_ردیف() -> dict[str, Any]:
    """داده آزمایشی با پوشش مقادیر تهی، متن فارسی و اعداد مختلط تولید می‌کند."""

    return {
        "national_id": "0000000000",
        "counter": "730000001",
        "first_name": "=SUM(A1:A2)",
        "last_name": "نجاتی",
        "gender": 1,
        "mobile": "۰۹۱۲۱۲۳۴۵۶۷",
        "reg_center": 0,
        "reg_status": 1,
        "group_code": "01",
        "student_type": "",
        "school_code": "12",
        "mentor_id": "MN-001",
        "mentor_name": "زهرا",
        "mentor_mobile": None,
        "allocation_date": None,
        "year_code": "۱۴۰۲",
    }


@retry(times=3, delay=0.1)
@pytest.mark.usefixtures("timing_control")
def test_excel_formula_injection_guard(
    tmp_path: Path, clean_redis_state_sync, db_session
) -> None:
    """مقدار آغازشده با '=' باید با پیشوند امن وارد فایل CSV شود."""

    db_session.execute(text("SELECT 1"))
    target_dir = tmp_path / clean_redis_state_sync.namespace
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "guarded.csv"

    writer = ExportWriter(
        formula_guard=True, sensitive_columns=("first_name", "last_name", "mentor_name")
    )
    rows = [_نمونه_ردیف()]
    result = writer.write_csv(rows, path_factory=lambda _: csv_path)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = list(csv.reader(handle))
    داده = reader[1][2]
    context = {"خانه": داده, "گزارش": result.excel_safety}
    assert داده.startswith("'=SUM"), f"گارد فرمول اعمال نشد: {context}"
    assert result.excel_safety.get("formula_guard") is True, f"فلگ ایمنی فرمول نادرست است: {context}"


@retry(times=3, delay=0.1)
@pytest.mark.usefixtures("timing_control")
def test_always_quote_persian_strings(
    tmp_path: Path, clean_redis_state_sync, db_session
) -> None:
    """همه مقادیر فارسی باید در CSV با علامت نقل‌قول احاطه شوند."""

    db_session.execute(text("SELECT 1"))
    csv_path = tmp_path / f"quoted-{clean_redis_state_sync.namespace}.csv"
    writer = ExportWriter(
        formula_guard=True, sensitive_columns=("first_name", "last_name", "mentor_name")
    )
    rows = [_نمونه_ردیف() | {"last_name": "مریم", "mentor_name": "سارا", "first_name": "پارسا"}]
    writer.write_csv(rows, path_factory=lambda _: csv_path)
    raw_text = csv_path.read_text(encoding="utf-8")
    context = {"نمونه": raw_text.splitlines()[1]}
    assert '"مریم"' in raw_text and '"سارا"' in raw_text and '"پارسا"' in raw_text, (
        f"نقل‌قول کامل برای متن فارسی رعایت نشده است: {context}"
    )


@retry(times=3, delay=0.1)
@pytest.mark.usefixtures("timing_control")
def test_rtl_direction_metadata(
    tmp_path: Path, clean_redis_state_sync, db_session
) -> None:
    """پرچم راست‌به‌چپ باید در فایل اکسل تولیدی تنظیم شود."""

    db_session.execute(text("SELECT 1"))
    xlsx_path = tmp_path / f"rtl-{clean_redis_state_sync.namespace}.xlsx"
    writer = ExportWriter(
        formula_guard=True, sensitive_columns=("first_name", "last_name", "mentor_name")
    )
    result = writer.write_xlsx([_نمونه_ردیف()], path_factory=lambda _: xlsx_path)

    workbook = openpyxl.load_workbook(xlsx_path)
    try:
        sheet = workbook.active
        context = {
            "rtl": sheet.sheet_view.rightToLeft,
            "excel_safety": result.excel_safety,
        }
        assert sheet.sheet_view.rightToLeft is True, f"وضعیت RTL در شیت فعال نیست: {context}"
        assert result.excel_safety.get("rtl") is True, f"شاخص RTL در گزارش ایمنی مفقود است: {context}"
    finally:
        workbook.close()
