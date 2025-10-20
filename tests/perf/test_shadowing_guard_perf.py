from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_no_shadowing import scan_repository


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_shadowing_guard_perf_budget() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations, telemetry = scan_repository(repo_root)
    context = {
        "violations": violations,
        "duration": telemetry["duration_seconds"],
        "peak_bytes": telemetry["peak_bytes"],
        "scanned": telemetry["scanned_files"],
    }
    assert not violations, f"خطاهای سایه‌زنی: {context}"
    assert telemetry["scanned_files"] > 100, f"دادهٔ ناکافی برای سنجش کارایی: {context}"
    assert telemetry["duration_seconds"] <= 5.0, f"بودجهٔ زمانی نقض شد: {context}"
    peak_mb = telemetry["peak_bytes"] / (1024 * 1024)
    assert peak_mb <= 128, f"مصرف حافظه بیش از حد مجاز است: {context}"
