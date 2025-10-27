"""Platform-specific uvloop guards."""

from __future__ import annotations

import pytest

from sma.ci_hardening.runtime import is_uvloop_supported


def test_skips_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """uvloop must be disabled on Windows."""

    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert not is_uvloop_supported()


def test_allows_on_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """uvloop may run on POSIX platforms."""

    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert is_uvloop_supported()
