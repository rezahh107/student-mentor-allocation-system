from __future__ import annotations

from tests.ops.conftest import get_debug_context

pytest_plugins = ("tests.ops.conftest",)


def test_manager_sees_only_own_center(build_ops_client, clean_state):
    client = build_ops_client(
        exports=[
            {"center_id": "123", "status_label": "موفق", "count": 7, "updated_at": "2024-01-01"},
            {"center_id": "456", "status_label": "جاری", "count": 2, "updated_at": "2024-01-01"},
        ],
        uploads=[
            {"center_id": "456", "phase_label": "شروع", "size_mb": 12, "updated_at": "2024-01-01"},
        ],
    )

    response = client.get("/ui/ops/exports", params={"role": "MANAGER", "center": "۴۵۶"})
    assert response.status_code == 200, get_debug_context(clean_state)
    body = response.text
    assert "456" in body and "123" not in body


def test_admin_sees_all(build_ops_client, clean_state):
    client = build_ops_client(
        exports=[
            {"center_id": "123", "status_label": "موفق", "count": 7, "updated_at": "2024-01-01"},
            {"center_id": "456", "status_label": "جاری", "count": 2, "updated_at": "2024-01-01"},
        ],
        uploads=[
            {"center_id": "456", "phase_label": "شروع", "size_mb": 12, "updated_at": "2024-01-01"},
        ],
    )

    response = client.get("/ui/ops/exports", params={"role": "ADMIN"})
    assert response.status_code == 200
    body = response.text
    assert "456" in body and "123" in body
