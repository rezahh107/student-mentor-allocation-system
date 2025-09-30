from __future__ import annotations

from tests.plugins.session_stats import get_session_stats


def test_no_skips(pytestconfig) -> None:
    stats = get_session_stats(pytestconfig)
    assert not stats.skipped, f"Skipped tests detected: {stats.skipped}"
    assert not stats.xfailed, f"XFailed tests detected: {stats.xfailed}"
    assert not stats.warnings, f"Warnings captured: {stats.warnings}"
