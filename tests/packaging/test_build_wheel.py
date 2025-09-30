from __future__ import annotations

from pathlib import Path

import pytest

from tests.packaging.conftest import (
    CommandResult,
    PackagingState,
    get_debug_context,
)


@pytest.mark.usefixtures("packaging_state")
def test_build_wheel_ok(packaging_state: PackagingState) -> None:
    wheel_dir = packaging_state.workspace
    result: CommandResult = packaging_state.run(
        (
            "python",
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "-w",
            str(wheel_dir),
        ),
        expect_success=True,
    )

    wheels = sorted(Path(wheel_dir).glob("*.whl"))
    context = get_debug_context(packaging_state, result)
    context.update({"wheel_files": [wheel.name for wheel in wheels]})
    assert wheels, f"Wheel build produced no artifacts. Context: {context}"
    artifact_name = wheels[0].name
    assert artifact_name.startswith("student_mentor_allocation_system-0.0.0"), (
        f"Unexpected wheel name {artifact_name}. Context: {context}"
    )
