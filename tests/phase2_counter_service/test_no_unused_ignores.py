from __future__ import annotations

from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORE_PATTERN = re.compile(r"#\s*type:\s*ignore(\[([^\]]+)\])?")
ALLOWED_ERROR_CODES = {
    "arg-type",
    "assignment",
    "attr-defined",
    "call-arg",
    "name-defined",
    "no-redef",
    "override",
    "return-value",
}
BANNED_ERROR_CODES = {"unused-ignore"}


@pytest.mark.parametrize("path", sorted(REPO_ROOT.rglob("*.py")))
def test_no_banned_type_ignore_codes(path: Path) -> None:
    """Ensure ``# type: ignore`` pragmas never mask unused-ignore warnings."""

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = IGNORE_PATTERN.search(line)
        if not match:
            continue
        codes = match.group(2)
        if not codes:
            # Bare ``# type: ignore`` is allowed for optional runtime dependencies.
            continue
        for code in (code.strip() for code in codes.split(",")):
            assert code not in BANNED_ERROR_CODES, (
                f"Forbidden mypy ignore code '{code}' in {path.relative_to(REPO_ROOT)}:{line_number}"
            )
            assert code in ALLOWED_ERROR_CODES, (
                f"Unexpected mypy ignore code '{code}' in {path.relative_to(REPO_ROOT)}:{line_number}"
            )
