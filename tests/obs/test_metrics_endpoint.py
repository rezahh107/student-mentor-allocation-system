from fastapi.testclient import TestClient

from sma.phase6_import_to_sabt.app.app_factory import create_application


def test_metrics_endpoint_is_public() -> None:
    client = TestClient(create_application())
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text.startswith("# HELP")
