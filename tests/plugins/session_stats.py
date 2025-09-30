from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pytest
from pytest import StashKey


GATE_NODEIDS = {
    "tests/ci/test_full_suite.py::test_pytest_collects_cleanly",
    "tests/ci/test_no_skips_gate.py::test_no_skips",
    "tests/ci/test_no_warnings_gate.py::test_no_warnings",
}


@dataclass
class SessionStats:
    """Aggregate runtime statistics for pytest session outcomes."""

    skipped: List[str] = field(default_factory=list)
    xfailed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def record_report(self, report: pytest.TestReport) -> None:
        nodeid = report.nodeid
        if report.skipped:
            if getattr(report, "wasxfail", False):
                self.xfailed.append(nodeid)
            else:
                self.skipped.append(nodeid)

    def record_warning(self, message: str) -> None:
        self.warnings.append(message)


SESSION_STATS = SessionStats()
SESSION_STATS_KEY: StashKey[SessionStats] = StashKey()


def get_session_stats(config: pytest.Config) -> SessionStats:
    return config.stash.setdefault(SESSION_STATS_KEY, SESSION_STATS)


def pytest_configure(config: pytest.Config) -> None:
    config.stash.setdefault(SESSION_STATS_KEY, SESSION_STATS)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    SESSION_STATS.record_report(report)


def pytest_warning_recorded(warning_message, when, nodeid, location) -> None:  # type: ignore[no-untyped-def]
    formatted = f"{warning_message.message}:{when}:{nodeid}:{location}"
    SESSION_STATS.record_warning(formatted)


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    if not GATE_NODEIDS:
        return
    gate_items: list[pytest.Item] = []
    regular_items: list[pytest.Item] = []
    gate_lookup = set(GATE_NODEIDS)
    for item in items:
        if item.nodeid in gate_lookup:
            gate_items.append(item)
        else:
            regular_items.append(item)
    items[:] = regular_items + gate_items
