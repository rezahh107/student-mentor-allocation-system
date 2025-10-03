from __future__ import annotations

from pathlib import Path

import pytest


def test_no_datetime_now_repo_wide(pytestconfig: pytest.Config) -> None:
    guard_payload = getattr(pytestconfig, "_repo_wall_clock_guard", None)
    assert guard_payload is not None, "wall clock guard payload missing"
    banned = guard_payload.get("banned", ())
    assert not banned, (
        "TIME_SOURCE_FORBIDDEN: «استفادهٔ مستقیم از زمان سیستم مجاز نیست؛ از Clock تزریق‌شده استفاده کنید.» "
        + ", ".join(str(item) for item in banned)
    )
    scanned = guard_payload.get("scanned", ())
    assert scanned, "wall clock guard must scan at least one source file"
    suffixes = {Path(path).suffix for path in scanned}
    assert suffixes == {".py"}, suffixes
