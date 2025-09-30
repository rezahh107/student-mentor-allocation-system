from __future__ import annotations

import pytest

from tests.packaging.conftest import CommandResult, PackagingState, get_debug_context

_ANCHOR = "AGENTS.md::Determinism & CI"
_TARGETS = (
    "tools/bom_guard.py",
    "tools/strip_bom.py",
    "tests/ci/conftest.py",
    "tests/ci/test_bom_guard.py",
    "tests/ci/test_ruff_gate.py",
    "tests/ci/test_mypy_strict.py",
    "tests/ci/test_pydocstyle_gate.py",
    "tests/export/test_xlsx_excel_safety.py",
    "tests/export/test_atomic_finalize.py",
    "tests/security/test_metrics_protection_all_apps.py",
    "tests/mw/test_middleware_order_all_apps.py",
    "tests/perf/test_perf_gates.py",
)


@pytest.mark.usefixtures("packaging_state")
def test_ruff_gate(packaging_state: PackagingState) -> None:
    command = ("python", "-m", "ruff", "check", *_TARGETS)
    result: CommandResult = packaging_state.run(command, expect_success=True)
    context = get_debug_context(packaging_state, result)
    context.update(
        {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "targets": _TARGETS,
            "evidence": _ANCHOR,
        }
    )
    assert "warning" not in (result.stdout or "").lower(), context
    assert result.returncode == 0, context
