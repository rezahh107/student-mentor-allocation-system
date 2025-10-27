"""Guards ensuring AGENTS manifests exist."""

from __future__ import annotations

from pathlib import Path

import pytest

from sma.ci_hardening.runtime import (
    RuntimeConfigurationError,
    ensure_agents_manifest,
)

_DEF_MESSAGE = (
    "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
)


def test_agents_manifest_detects_existing(tmp_path: Path) -> None:
    """Existing manifests should be detected without error."""

    manifest = tmp_path / "AGENTS.md"
    manifest.write_text("# instructions", encoding="utf-8")
    found = ensure_agents_manifest([tmp_path])
    assert found == manifest


def test_agents_manifest_missing(tmp_path: Path) -> None:
    """Missing manifests must raise the specified Persian error."""

    with pytest.raises(RuntimeConfigurationError) as exc:
        ensure_agents_manifest([tmp_path])
    assert str(exc.value) == _DEF_MESSAGE
