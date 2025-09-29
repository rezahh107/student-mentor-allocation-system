from __future__ import annotations

from tests.ops.conftest import get_debug_context

pytest_plugins = ("tests.ops.conftest",)


def test_empty_and_error_states(build_ops_client, clean_state):
    client = build_ops_client(exports=[], uploads=[])
    exports_resp = client.get("/ui/ops/exports")
    body = exports_resp.text
    assert "هیچ برون‌سپاری" in body, get_debug_context(clean_state)
    assert "در حال بارگذاری…" in body

    failing_client = build_ops_client(exports=[], uploads=[], fail_exports=True, fail_uploads=True)
    resp_error = failing_client.get("/ui/ops/exports")
    assert "بازیابی داده‌های برون‌سپاری با خطا" in resp_error.text
    resp_upload_error = failing_client.get("/ui/ops/uploads")
    assert "بازیابی داده‌های بارگذاری" in resp_upload_error.text
