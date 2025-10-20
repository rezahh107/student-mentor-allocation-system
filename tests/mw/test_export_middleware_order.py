from sma.phase6_import_to_sabt.compat import TestClient
from sma.phase6_import_to_sabt.metrics import reset_registry

from tests.export.helpers import build_export_app, make_row


def test_middleware_order_export_endpoint(tmp_path) -> None:
    app, runner, metrics = build_export_app(tmp_path, [make_row(idx=1)])
    client = TestClient(app)

    response = client.get(
        "/export/sabt/v1",
        params={"year": 1402, "center": 1, "format": "csv"},
        headers={"Idempotency-Key": "idem-mw", "X-Role": "ADMIN"},
    )
    assert response.status_code == 200, response.text
    chain = response.json()["middleware_chain"]
    assert chain == ["ratelimit", "idempotency", "auth"]

    runner.redis.flushdb()
    reset_registry(metrics.registry)
