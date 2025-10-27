"""Python interpreter guards."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from sma.ci_hardening.runtime import RuntimeConfigurationError, ensure_python_311


def test_python_version_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python versions outside 3.11 must raise a Persian error."""

    monkeypatch.setattr(
        sys, "version_info", SimpleNamespace(major=3, minor=13, micro=0)
    )
    with pytest.raises(RuntimeConfigurationError) as exc:
        ensure_python_311()
    assert "نسخهٔ پایتون پشتیبانی نمی‌شود" in str(exc.value)
