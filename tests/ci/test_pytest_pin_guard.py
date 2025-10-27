"""Pytest version guard tests."""

from __future__ import annotations

import types

import pytest

import scripts.check_pytest_version as checker


def test_conflict_fails_persian(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Version mismatches must produce the Persian conflict message."""

    fake_pytest = types.SimpleNamespace(__version__="7.4.2")
    monkeypatch.setattr(checker, "pytest", fake_pytest)
    with pytest.raises(SystemExit) as exc:
        checker.check_pytest_version()
    assert exc.value.code == 1
    captured = capsys.readouterr().err
    assert "تعارض نسخهٔ pytest" in captured


def test_expected_version_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matching versions should produce the OK message."""

    fake_pytest = types.SimpleNamespace(__version__=checker.EXPECTED_VERSION)
    monkeypatch.setattr(checker, "pytest", fake_pytest)
    checker.check_pytest_version()
    captured = capsys.readouterr().out
    assert f"✅ pytest version OK: {checker.EXPECTED_VERSION}" in captured
