"""غیرفعال‌سازی پیش‌فرض تست‌های کارایی در محیط‌های CI بدون پرچم صریح."""
from __future__ import annotations

import os

import pytest


if os.environ.get("RUN_PERFORMANCE_SUITE", "").strip().lower() not in {"1", "true", "on"}:
    pytest.skip(
        "PERF_DISABLED: تست‌های کارایی به‌صورت پیش‌فرض در این محیط اجرا نمی‌شوند.",
        allow_module_level=True,
    )

