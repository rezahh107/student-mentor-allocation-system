"""Smoke and end-to-end checks with Hypothesis fallbacks."""
from __future__ import annotations

import json

import pytest


@pytest.mark.smoke
def test_smoke_file_roundtrip(tmp_path) -> None:
    """Basic smoke test without optional dependencies."""

    sample_path = tmp_path / "smoke.txt"
    sample_path.write_text("ready\n", encoding="utf-8")
    assert sample_path.read_text(encoding="utf-8").strip() == "ready"


@pytest.mark.smoke
@pytest.mark.e2e
def test_json_roundtrip_property(tmp_path) -> None:
    """Property-based validation guarded by Hypothesis availability."""

    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis نصب نیست (محلی)")
    strategies = pytest.importorskip(
        "hypothesis.strategies", reason="hypothesis نصب نیست (محلی)"
    )
    given = hypothesis.given
    text_strategy = strategies.text(alphabet=strategies.characters())

    @given(text_strategy)
    def _roundtrip(payload: str) -> None:
        envelope = {"payload": payload}
        artifact = tmp_path / "payload.json"
        artifact.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
        assert loaded == envelope

    _roundtrip()
