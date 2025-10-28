from __future__ import annotations

import pathlib
import re
from collections.abc import Iterable

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[2]


def _iter_pin_versions(path: pathlib.Path) -> Iterable[str]:
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n")
    pattern = re.compile(r"^tenacity==(?P<version>[^\\\s]+)", re.MULTILINE)
    return pattern.findall(normalized)


def _expected_version() -> str:
    requirement_path = ROOT / "requirements.in"
    versions = list(_iter_pin_versions(requirement_path))
    if len(versions) != 1:
        raise AssertionError(
            f"requirements.in must define a single tenacity pin, found: {versions}"
        )
    return versions[0]


@pytest.mark.parametrize(
    "relative_path",
    (
        pathlib.Path("requirements.txt"),
        pathlib.Path("requirements-dev.txt"),
        pathlib.Path("constraints.txt"),
        pathlib.Path("constraints-dev.txt"),
        pathlib.Path("constraints-win.txt"),
    ),
)
def test_tenacity_pin_matches_source(relative_path: pathlib.Path) -> None:
    target_path = ROOT / relative_path
    versions = list(_iter_pin_versions(target_path))
    assert versions, f"Expected to find a tenacity pin in {relative_path}, got none"

    unique_versions = {version.strip() for version in versions if version.strip()}
    assert len(unique_versions) == 1, (
        f"Found multiple tenacity versions in {relative_path}: {sorted(unique_versions)}"
    )

    expected = _expected_version()
    assert unique_versions == {expected}, (
        f"{relative_path} pins tenacity to {sorted(unique_versions)}, expected {expected}"
    )
