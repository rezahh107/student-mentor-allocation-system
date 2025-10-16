"""Artifact writers with atomic I/O and Excel safety."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from .normalization import normalize_and_guard, normalize_text


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically with CRLF endings."""
    ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".part")
    data = content.replace("\n", "\r\n")
    with open(tmp_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically."""
    ensure_parent(path)
    tmp_path = path.with_suffix(path.suffix + ".part")
    with open(tmp_path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def ensure_parent(path: Path) -> None:
    """Ensure parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(report: dict[str, Any], path: Path) -> None:
    """Write sync report as JSON with CRLF line endings."""
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    atomic_write_text(path, serialized + "\n")


def write_csv(report: dict[str, Any], path: Path) -> None:
    """Write CSV artifact with Excel-safety rules."""
    rows = _build_csv_rows(report)
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    for row in rows:
        writer.writerow([normalize_and_guard(str(value)) for value in row])
    payload = buffer.getvalue()
    buffer.close()
    # Prepend UTF-8 BOM
    data = ("\ufeff" + payload).encode("utf-8")
    atomic_write_bytes(path, data)


def _build_csv_rows(report: dict[str, Any]) -> list[list[Any]]:
    """Construct rows for CSV export."""
    headers = [
        "correlation_id",
        "status",
        "exit_code",
        "path",
        "remote_expected",
        "remote_actual",
        "branch_checked",
        "head_local",
        "head_remote",
        "ahead",
        "behind",
        "dirty",
        "untracked_count",
        "tags_aligned",
        "shallow",
        "detached",
        "timing_ms",
    ]
    row = [
        report.get("correlation_id", ""),
        report.get("status", ""),
        report.get("exit_code", ""),
        report.get("path", ""),
        report.get("remote_expected", ""),
        report.get("remote_actual", ""),
        report.get("branch_checked", ""),
        report.get("head_local", ""),
        report.get("head_remote", ""),
        report.get("ahead", ""),
        report.get("behind", ""),
        report.get("dirty", ""),
        report.get("untracked_count", ""),
        report.get("tags_aligned", ""),
        report.get("shallow", ""),
        report.get("detached", ""),
        report.get("timing_ms", ""),
    ]
    return [headers, row]


def write_markdown(report: dict[str, Any], path: Path) -> None:
    """Write human-readable markdown summary in Persian."""
    status_persian = _status_to_persian(report.get("status", ""))
    lines = [
        f"# گزارش همگام‌سازی مخزن",
        f"- شناسهٔ همبستگی: {normalize_text(str(report.get('correlation_id', '')))}",
        f"- وضعیت: {status_persian}",
        f"- مسیر بررسی‌شده: {normalize_text(str(report.get('path', '')))}",
        f"- شاخهٔ بررسی‌شده: {normalize_text(str(report.get('branch_checked', '')))}",
        f"- جلوتر: {report.get('ahead', 0)} | عقب‌تر: {report.get('behind', 0)}",
        f"- وضعیت تمیزی: {'پاک' if not report.get('dirty', False) else 'تغییر دارد'}",
        f"- برچسب‌ها هم‌سو هستند: {'بله' if report.get('tags_aligned', False) else 'خیر'}",
        f"- زمان اجرا (ms): {report.get('timing_ms', 0)}",
    ]
    atomic_write_text(path, "\n".join(lines) + "\n")


def _status_to_persian(status: str) -> str:
    mapping = {
        "in_sync": "کاملاً همگام",
        "behind": "نیاز به pull",
        "ahead": "نیاز به push",
        "diverged": "شاخه‌ها واگرا هستند",
        "dirty": "تغییرات ثبت‌نشده",
        "remote_mismatch": "ناهماهنگی مخزن دور",
        "submodule_drift": "انحراف زیرماژول/LFS",
        "shallow_or_detached": "مخزن ناقص یا HEAD جدا شده",
        "error": "خطای اجرایی",
    }
    return mapping.get(status, "نامشخص")
