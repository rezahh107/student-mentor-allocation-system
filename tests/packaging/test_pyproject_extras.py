from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.packaging.conftest import (
    CommandResult,
    PackagingState,
    get_debug_context,
)

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


@pytest.mark.usefixtures("packaging_state")
def test_install_extras_non_interactive(packaging_state: PackagingState) -> None:
    raw_pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    data = tomllib.loads(raw_pyproject)
    project_block = data.get("project", {})
    extras = project_block.get("optional-dependencies", {})

    context = get_debug_context(packaging_state, None)
    context.update({"extras": extras})

    assert {"dev", "test"}.issubset(extras), (
        "Missing required extras declared in pyproject.toml. Context: " f"{context}"
    )
    assert extras["test"], f"Test extras must not be empty. Context: {context}"
    assert extras["dev"], f"Dev extras must not be empty. Context: {context}"

    result: CommandResult = packaging_state.run(
        ("python", "setup.py", "--version"),
        expect_success=False,
    )
    message = (result.stderr or result.stdout).strip()
    failure_context = get_debug_context(packaging_state, result)
    assert result.returncode != 0, f"setup.py should fail-fast. Context: {failure_context}"
    expected_fragment = "اجرای setup.py پشتیبانی نمی‌شود"
    assert expected_fragment in message, f"Missing Persian guidance. Context: {failure_context}"
    assert "pyproject.toml" in message, f"Message must point to pyproject.toml. Context: {failure_context}"
