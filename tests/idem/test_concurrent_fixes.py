from __future__ import annotations

import threading
from pathlib import Path

from repo_auditor_lite.files import write_atomic


def test_atomic_write_single_writer(clean_state) -> None:
    target = Path(clean_state["tmp"]) / "concurrent.txt"
    barrier = threading.Barrier(3)
    results: list[str] = []

    def worker(value: str) -> None:
        barrier.wait()
        outcome = write_atomic(target, value)
        results.append(outcome)

    threads = [threading.Thread(target=worker, args=("مقدار",)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("written") == 1
    assert results.count("unchanged") == 2
    assert target.read_text(encoding="utf-8") == "مقدار"
