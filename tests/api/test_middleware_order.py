from __future__ import annotations

import pytest

from sma.phase6_import_to_sabt.api import ExportAPI, ExportLogger, ExporterMetrics
from sma.phase7_release.deploy import ReadinessGate

from tests.phase7_utils import DummyRunner


@pytest.fixture
def clean_state():
    yield


def test_rate_limit_idem_auth_order_all_routes(tmp_path, clean_state):
    api = ExportAPI(
        runner=DummyRunner(output_dir=tmp_path),
        signer=lambda path, expires_in=0: path,
        metrics=ExporterMetrics(),
        logger=ExportLogger(),
        metrics_token="secret",
        readiness_gate=ReadinessGate(clock=lambda: 0.0),
    )
    router = api.create_router()

    def _dependency_order(route_path: str, method: str) -> list[str]:
        for route in router.routes:
            if getattr(route, "path", "") == route_path and method in getattr(route, "methods", set()):
                return [dep.call.__name__ for dep in route.dependant.dependencies]
        raise AssertionError(f"route {route_path} not found")

    exports_order = _dependency_order("/exports", "POST")
    health_order = _dependency_order("/healthz", "GET")
    expected_exports = ["rate_limit_dependency", "idempotency_dependency", "auth_dependency"]
    expected_health = [
        "rate_limit_dependency",
        "optional_idempotency_dependency",
        "optional_auth_dependency",
    ]
    assert exports_order == expected_exports
    assert health_order == expected_health
