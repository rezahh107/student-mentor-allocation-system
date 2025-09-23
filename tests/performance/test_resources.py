# -*- coding: utf-8 -*-
from __future__ import annotations

import gc
import platform
from typing import Optional

import pytest

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore

if psutil is None:
    try:
        import resource  # type: ignore
    except ImportError:  # pragma: no cover - not available on Windows
        resource = None  # type: ignore
else:
    resource = None  # type: ignore

from src.domain.allocation.engine import AllocationEngine
from tests.factories import make_mentor, make_student


def get_memory_usage() -> Optional[int]:
    """Return RSS usage in bytes when metrics are available."""

    if psutil is not None:
        return psutil.Process().memory_info().rss

    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports ru_maxrss in bytes already, Linux in kilobytes
        if platform.system() != "Darwin":
            usage *= 1024
        return usage

    return None


@pytest.mark.resources
def test_memory_profile_small_batch():
    rss_before = get_memory_usage()
    if rss_before is None:
        pytest.skip("Memory profiling requires psutil or resource support")

    eng = AllocationEngine()
    mentors = [make_mentor(i + 1) for i in range(100)]

    for i in range(2000):
        eng.select_best(make_student(str(i)), mentors)

    gc.collect()
    rss_after = get_memory_usage()
    assert rss_after is not None

    # Accept up to ~200MB increase depending on OS units
    assert (rss_after - rss_before) < 200 * 1024 * 1024
