from __future__ import annotations

import pytest

from tests.ops.conftest import get_debug_context

pytest_plugins = ("tests.ops.conftest",)


@pytest.mark.parametrize("path", ["/ui/ops/home", "/ui/ops/exports", "/ui/ops/uploads", "/ui/ops/slo"])
def test_ops_pages_render_rtl_no_pii(build_ops_client, clean_state, path):
    client = build_ops_client(
        exports=[{"center_id": "123", "status_label": "موفق", "count": 4, "updated_at": "2024-01-01"}],
        uploads=[{"center_id": "123", "phase_label": "شروع", "size_mb": 12, "updated_at": "2024-01-01"}],
    )

    response = client.get(path)
    assert response.status_code == 200, get_debug_context(clean_state)
    body = response.text
    assert 'lang="fa-IR"' in body and 'dir="rtl"' in body
    assert "نام" not in body  # no personal data terms
    assert "کد ملی" not in body
    assert "badge" in body


def test_center_validation_handles_edge_values(build_ops_client):
    client = build_ops_client(exports=[], uploads=[])
    for value in (None, "", "0", "۰", "\u200c"):
        assert client.get("/ui/ops/exports", params={"center": value}).status_code == 200

    assert client.get("/ui/ops/exports", params={"center": "001"}).status_code == 400


def test_invalid_role_rejected(build_ops_client):
    client = build_ops_client(exports=[], uploads=[])
    response = client.get("/ui/ops/home", params={"role": "GUEST"})
    assert response.status_code == 403
    assert "نقش" in response.text
