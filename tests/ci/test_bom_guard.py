from __future__ import annotations

import json

import pytest

from tests.packaging.conftest import CommandResult, PackagingState, get_debug_context
from tools.bom_guard import BOM

_ANCHOR = "AGENTS.md::Determinism & CI"


@pytest.mark.usefixtures("packaging_state")
def test_no_bom_in_source_tree(packaging_state: PackagingState) -> None:
    result: CommandResult = packaging_state.run(
        ("python", "tools/bom_guard.py", "--json"),
        expect_success=True,
    )
    payload = json.loads(result.stdout or "{}")
    context = get_debug_context(packaging_state, result)
    context.update({"payload": payload, "evidence": _ANCHOR})
    assert payload.get("bom_findings") == [], context

    bom_target = packaging_state.workspace / "bom-fixture.json"
    bom_target.write_bytes(BOM + b"{}")
    failing: CommandResult = packaging_state.run(
        ("python", "tools/bom_guard.py", "--paths", str(bom_target)),
        expect_success=False,
    )
    failing_context = get_debug_context(packaging_state, failing)
    failing_context.update({"stdout": failing.stdout, "stderr": failing.stderr})
    message = (failing.stdout or failing.stderr or "{}").strip()
    assert "bom_findings" in message, failing_context
    assert str(bom_target) in message, failing_context
