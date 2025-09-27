import math

from phase6_import_to_sabt.sanitization import deterministic_jitter
from phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from phase6_import_to_sabt.xlsx.retry import retry_with_backoff


def test_retry_jitter_and_metrics_without_sleep() -> None:
    metrics = build_import_export_metrics()
    delays: list[float] = []
    attempts: list[int] = []

    def sleeper(delay: float) -> None:
        delays.append(delay)

    def operation(attempt: int) -> str:
        attempts.append(attempt)
        if attempt < 3:
            raise OSError("transient")
        return "ok"

    result = retry_with_backoff(
        operation,
        attempts=3,
        base_delay=0.02,
        seed="fsync_test",
        metrics=metrics,
        format_label="xlsx",
        sleeper=sleeper,
    )

    assert result == "ok"
    assert attempts == [1, 2, 3]
    expected_first = deterministic_jitter(0.02, 1, "fsync_test")
    expected_second = deterministic_jitter(0.02, 2, "fsync_test")
    assert math.isclose(delays[0], expected_first, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(delays[1], expected_second, rel_tol=0.0, abs_tol=1e-9)
    retry_metric = metrics.retry_total.labels(operation="fsync_test", format="xlsx")._value.get()
    assert retry_metric == 2
    exhaustion_metric = metrics.retry_exhausted_total.labels(operation="fsync_test", format="xlsx")._value.get()
    assert exhaustion_metric == 0
