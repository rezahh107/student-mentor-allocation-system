"""تست‌های طلایی با مقایسهٔ بایت‌به‌بایت و حساس به CRLF/BOM."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

GOLDEN_ROOT = Path(__file__).parent / "golden"
FAILURE_TOKEN = "failing"
EMPTY_MESSAGE = "دایرکتوری طلایی خالی است؛ ابتدا نمونه بسازید."


def _is_enabled(flag: str | None) -> bool:
    """Determine if an environment flag should be considered enabled."""

    if flag is None:
        return False
    lowered = flag.strip().lower()
    return lowered not in {"", "0", "false", "no"}


def _collect_cases(include_failures: bool) -> list[pytest.ParameterSet]:
    """Return parametrized cases for available golden directories."""

    if not GOLDEN_ROOT.exists():
        pytest.xfail(EMPTY_MESSAGE)
    case_dirs = [path for path in sorted(GOLDEN_ROOT.iterdir()) if path.is_dir()]
    if not case_dirs:
        pytest.xfail(EMPTY_MESSAGE)

    params: list[pytest.ParameterSet] = []
    for case_dir in case_dirs:
        expected = case_dir / "expected.csv"
        produced = case_dir / "produced.csv"
        if not expected.exists() or not produced.exists():
            pytest.fail(f"پرونده‌های طلایی در {case_dir.name} ناقص هستند.")
        case_id = case_dir.name
        if FAILURE_TOKEN in case_id:
            if include_failures:
                params.append(
                    pytest.param(
                        expected,
                        produced,
                        id=case_id,
                        marks=pytest.mark.xfail(reason="نمونهٔ کنترل‌شده برای شکست عمدی"),
                    )
                )
            continue
        params.append(pytest.param(expected, produced, id=case_id))

    if not params:
        pytest.xfail(EMPTY_MESSAGE)
    return params


INCLUDE_FAILING = _is_enabled(os.getenv("RUN_FAILING_GOLDEN"))
PARAMETERS = _collect_cases(INCLUDE_FAILING)


@pytest.mark.golden
@pytest.mark.parametrize("expected_path, produced_path", PARAMETERS)
def test_golden_bytes(expected_path: Path, produced_path: Path) -> None:
    """Ensure exporter outputs remain byte-for-byte identical."""

    expected_bytes = expected_path.read_bytes()
    produced_bytes = produced_path.read_bytes()
    if expected_bytes != produced_bytes:
        pytest.fail("مقایسهٔ طلایی شکست خورد؛ محتوای تولیدی با نسخهٔ مرجع برابر نیست.")
