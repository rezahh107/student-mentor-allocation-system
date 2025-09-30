from __future__ import annotations

import pytest

from tests.packaging.conftest import CommandResult, PackagingState, get_debug_context

_ANCHOR = "AGENTS.md::Determinism & CI"


@pytest.mark.usefixtures("packaging_state")
def test_mypy_strict(packaging_state: PackagingState) -> None:
    command = ("python", "-m", "mypy", "--config-file", "pyproject.toml")
    result: CommandResult = packaging_state.run(command, expect_success=True)
    context = get_debug_context(packaging_state, result)
    context.update({"stdout": result.stdout, "stderr": result.stderr, "evidence": _ANCHOR})
    assert "Success: no issues found" in (result.stdout or ""), context
