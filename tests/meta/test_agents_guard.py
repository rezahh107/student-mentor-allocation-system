from __future__ import annotations

import pytest

from windows_launcher.launcher import LauncherError, ensure_agents_manifest


def test_agents_md_required(tmp_path):
    with pytest.raises(LauncherError) as excinfo:
        ensure_agents_manifest(tmp_path)
    assert excinfo.value.code == "AGENTS_MISSING"
    assert excinfo.value.message == (
        "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
    )

    manifest = tmp_path / "AGENTS.md"
    manifest.write_text("demo", encoding="utf-8")
    assert ensure_agents_manifest(tmp_path) == manifest
