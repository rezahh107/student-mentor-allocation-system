"""Golden regression tests with byte-level equality checks for exporter artifacts."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

GOLDEN_ROOT = Path(__file__).parent / "golden_cases"
FAILURE_TOKEN = "failing"
EMPTY_MESSAGE = "دایرکتوری طلایی خالی است؛ ابتدا نمونه بسازید."


def _truthy(value: str | None) -> bool:
    """Interpret environment variables for boolean intent."""

    if value is None:
        return False
    lowered = value.strip().lower()
    return lowered not in {"", "0", "false", "no", "n"}


def _discover_pairs(include_failures: bool) -> list[pytest.ParameterSet]:
    """Return pytest parameters for available golden cases."""

    params: list[pytest.ParameterSet] = []
    if not GOLDEN_ROOT.exists():
        pytest.xfail(EMPTY_MESSAGE)
    available_dirs = [path for path in sorted(GOLDEN_ROOT.iterdir()) if path.is_dir()]
    if not available_dirs:
        pytest.xfail(EMPTY_MESSAGE)
    for case_dir in available_dirs:
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


INCLUDE_FAILING = _truthy(os.environ.get("RUN_FAILING_GOLDEN"))
PARAMETERS = _discover_pairs(INCLUDE_FAILING)


@pytest.mark.golden
@pytest.mark.parametrize("expected_path, produced_path", PARAMETERS)
def test_golden_bytes(expected_path: Path, produced_path: Path) -> None:
    """Ensure that golden files match byte-for-byte, including newlines."""

    # Spec compliance: golden equality must remain بایت‌محور و حساس به CRLF/BOM.
    expected_bytes = expected_path.read_bytes()
    produced_bytes = produced_path.read_bytes()
    if expected_bytes != produced_bytes:
        pytest.fail(
            "مقایسهٔ طلایی شکست خورد؛ محتوای تولیدی با نسخهٔ مرجع برابر نیست."
        )
