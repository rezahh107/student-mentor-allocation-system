"""Ensure the ``.env.example`` generator writes atomically."""

from __future__ import annotations

from pathlib import Path

from sma.ci_hardening.settings import generate_env_example


def test_atomic_write(tmp_path: Path) -> None:
    """Generator should leave no partial files behind."""

    target = tmp_path / ".env.example"
    result = generate_env_example(target)
    assert result == target
    assert target.exists()
    assert not (tmp_path / ".env.example.part").exists()
    snapshot = target.read_text(encoding="utf-8")
    regenerated = generate_env_example(target)
    assert regenerated == target
    assert target.read_text(encoding="utf-8") == snapshot
