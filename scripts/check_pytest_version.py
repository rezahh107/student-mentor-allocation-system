"""Check for pytest version conflicts."""

from __future__ import annotations

import sys

import pytest

EXPECTED_VERSION = "7.4.3"


def check_pytest_version() -> None:
    """Verify single pytest version."""

    actual = pytest.__version__
    if actual != EXPECTED_VERSION:
        print(
            "❌ تعارض نسخهٔ pytest شناسایی شد؛ انتظار 7.4.3 اما "
            f"{actual} یافت شد. تنها یک نسخه باید در constraints قفل شود.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"✅ pytest version OK: {actual}")


if __name__ == "__main__":
    check_pytest_version()
