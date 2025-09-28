import time

from automation_audit.cli import compute_correlation_id


def test_latency_budget(tmp_path):
    start = time.perf_counter()
    for _ in range(1000):
        compute_correlation_id(tmp_path)
    duration = time.perf_counter() - start
    assert duration < 0.25
