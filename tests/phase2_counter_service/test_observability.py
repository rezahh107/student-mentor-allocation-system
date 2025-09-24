# -*- coding: utf-8 -*-
from __future__ import annotations

import socket
import time
import urllib.request

import pytest
from prometheus_client import CollectorRegistry

from src.phase2_counter_service import metrics as metrics_mod
from src.phase2_counter_service import observability as observability_mod
from src.phase2_counter_service.metrics import CounterMeters
from src.phase2_counter_service.observability import MetricsServer, metrics_server


def _gauge_value(gauge):
    return gauge._value.get()  # type: ignore[attr-defined]


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fetch_metrics(port: int) -> str:
    deadline = time.time() + 2
    url = f"http://127.0.0.1:{port}/metrics"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                return response.read().decode("utf-8")
        except OSError:
            time.sleep(0.05)
    raise AssertionError("metrics endpoint not reachable")


@pytest.fixture()
def isolated_meters(monkeypatch) -> CounterMeters:
    registry = CollectorRegistry()
    meters = CounterMeters(registry)
    monkeypatch.setattr(metrics_mod, "DEFAULT_METERS", meters)
    monkeypatch.setattr(observability_mod, "DEFAULT_METERS", meters)
    return meters


def test_metrics_server_sets_gauges(isolated_meters: CounterMeters):
    server = MetricsServer(isolated_meters)
    server.start(_reserve_port())
    assert _gauge_value(isolated_meters.exporter_gauge) == 1.0
    assert _gauge_value(isolated_meters.http_gauge) == 1.0
    server.stop()
    assert _gauge_value(isolated_meters.exporter_gauge) == 0.0
    assert _gauge_value(isolated_meters.http_gauge) == 0.0


def test_metrics_server_idempotent_start(isolated_meters: CounterMeters):
    server = MetricsServer(isolated_meters)
    port = _reserve_port()
    server.start(port)
    server.start(port)
    assert _gauge_value(isolated_meters.exporter_gauge) == 1.0
    server.stop()


def test_metrics_server_context_manager(isolated_meters: CounterMeters):
    with metrics_server(_reserve_port(), meters=isolated_meters) as server:
        assert _gauge_value(isolated_meters.exporter_gauge) == 1.0
        assert server.port is not None
    assert _gauge_value(isolated_meters.exporter_gauge) == 0.0


def test_metrics_server_graceful_shutdown_http(isolated_meters: CounterMeters):
    server = MetricsServer(isolated_meters)
    port = _reserve_port()
    server.start(port)
    payload = _fetch_metrics(server.port or port)
    assert "counter_exporter_health" in payload
    server.stop()
    assert server.port is None
    assert _gauge_value(isolated_meters.exporter_gauge) == 0.0
    assert _gauge_value(isolated_meters.http_gauge) == 0.0
