from __future__ import annotations

import time
import uuid

import psutil
import pytest

from phase2_uploads.logging_utils import get_debug_context

TARGET_SIZE = 50 * 1024 * 1024
_WARMED = False


@pytest.fixture(scope="module")
def large_csv(tmp_path_factory):
    base = tmp_path_factory.mktemp("uploads-perf")
    path = base / "large_roster.csv"
    header = (
        "student_id,school_code,mobile,national_id,first_name,last_name\r\n"
    ).encode("utf-8")
    student_suffix = ",123,09123456789,0012345678,محمد,کاظمی\r\n"
    suffix_bytes = student_suffix.encode("utf-8")
    base_student = "1" * 60000
    row_template = f"{base_student}{student_suffix}".encode("utf-8")
    minimum_row = len("1".encode("utf-8")) + len(suffix_bytes)
    with path.open("wb") as handle:
        handle.write(header)
        written = len(header)
        data_rows = 0
        # keep enough room for the adjustable final row
        while written + len(row_template) + minimum_row <= TARGET_SIZE:
            handle.write(row_template)
            written += len(row_template)
            data_rows += 1
        remaining = TARGET_SIZE - written
        if remaining < minimum_row:
            # ensure at least one row space
            written -= len(row_template)
            data_rows -= 1
            remaining = TARGET_SIZE - written
        filler_length = remaining - len(suffix_bytes)
        final_row = f"{'1' * filler_length}{student_suffix}".encode("utf-8")
        handle.write(final_row)
        written += len(final_row)
        data_rows += 1
    assert written == TARGET_SIZE
    return path, data_rows


def _run_large_upload(uploads_app, file_path, rows_expected):
    global _WARMED
    with file_path.open("rb") as source:
        file_bytes = source.read()
    service = uploads_app.app.state.upload_service
    recorded: list[float] = []
    metrics_cls = service.metrics.__class__
    original_record_success = metrics_cls.record_success

    def _capture_record_success(self, fmt, duration, size_bytes):
        recorded.append(duration)
        return original_record_success(self, fmt, duration, size_bytes)

    metrics_cls.record_success = _capture_record_success
    boundary = f"----perf{uuid.uuid4().hex}"
    segments = [
        (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"profile\"\r\n\r\n"
            "ROSTER_V1\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"year\"\r\n\r\n"
            "1402\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{file_path.name}\"\r\n"
            "Content-Type: text/csv\r\n\r\n"
        ).encode("utf-8")
        + file_bytes
        + b"\r\n",
    ]
    segments.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(segments)
    common_headers = {
        "X-Namespace": "tests-perf",
        "Authorization": "Bearer token",
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": str(len(body)),
    }
    if not _WARMED:
        warm_headers = {
            **common_headers,
            "Idempotency-Key": f"warm-{uuid.uuid4().hex}",
            "X-Request-ID": f"RID-{uuid.uuid4().hex}",
        }
        warm_response = uploads_app.request(
            "POST",
            "/uploads",
            headers=warm_headers,
            content=body,
        )
        assert warm_response.status_code == 200, get_debug_context({"phase": "warmup"})
        _WARMED = True
        recorded.clear()
    headers = {
        **common_headers,
        "Idempotency-Key": f"perf-{uuid.uuid4().hex}",
        "X-Request-ID": f"RID-{uuid.uuid4().hex}",
    }
    process = psutil.Process()
    baseline = process.memory_info().rss
    start = time.perf_counter()
    try:
        response = uploads_app.request(
            "POST",
            "/uploads",
            headers=headers,
            content=body,
        )
        duration = recorded[-1] if recorded else time.perf_counter() - start
        rss_after = process.memory_info().rss
        memory_delta = max(0, rss_after - baseline)
        context = get_debug_context(
            {
                "duration": duration,
                "baseline": baseline,
                "rss_after": rss_after,
                "memory_delta": memory_delta,
                "rows": rows_expected,
            }
        )
        assert response.status_code == 200, context
        manifest = response.json()["manifest"]
        assert manifest["record_count"] == rows_expected, context
        return duration, memory_delta
    finally:
        metrics_cls.record_success = original_record_success


def test_p95_latency_under_budget(uploads_app, large_csv):
    file_path, rows = large_csv
    duration, _ = _run_large_upload(uploads_app, file_path, rows)
    assert duration <= 6.0, get_debug_context({"duration": duration})


def test_memory_under_budget(uploads_app, large_csv):
    file_path, rows = large_csv
    _, memory_delta = _run_large_upload(uploads_app, file_path, rows)
    assert memory_delta <= 200 * 1024 * 1024, get_debug_context(
        {"memory_delta": memory_delta}
    )
