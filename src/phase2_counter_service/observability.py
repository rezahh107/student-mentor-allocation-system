# -*- coding: utf-8 -*-
"""Metrics exporter lifecycle management."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from prometheus_client import CollectorRegistry, make_wsgi_app
from prometheus_client.exposition import ThreadingWSGIServer
from wsgiref.simple_server import WSGIRequestHandler

from .metrics import CounterMeters, DEFAULT_METERS


class _SilentHandler(WSGIRequestHandler):
    """WSGI handler that suppresses the standard HTTP request logs."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: D401
        # Prometheus scrapes occur frequently and flood stderr; silence them.
        return


class MetricsServer:
    """Controls Prometheus exporter lifecycle with gauges for health."""

    def __init__(self, meters: CounterMeters = DEFAULT_METERS) -> None:
        self._meters = meters
        self._registry: CollectorRegistry = meters.registry
        self._lock = threading.Lock()
        self._server: ThreadingWSGIServer | None = None
        self._thread: threading.Thread | None = None
        self._port: Optional[int] = None

    def start(self, port: int) -> None:
        with self._lock:
            if self._server is not None:
                return
            app = make_wsgi_app(self._registry)
            server = ThreadingWSGIServer(("0.0.0.0", port), _SilentHandler)  # nosec B104
            server.allow_reuse_address = True
            server.daemon_threads = True
            server.set_app(app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            try:
                thread.start()
            except Exception:  # pragma: no cover - defensive
                server.server_close()
                raise
            self._server = server
            self._thread = thread
            self._port = int(server.server_address[1])
            self._meters.http_started(1.0)
            self._meters.exporter_health(1.0)

    def stop(self) -> None:
        with self._lock:
            if self._server is None:
                return
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._port = None
            server.shutdown()
            if thread is not None:
                thread.join(timeout=5)
            server.server_close()
            self._meters.exporter_health(0.0)
            self._meters.http_started(0.0)

    @property
    def port(self) -> Optional[int]:
        """Return the bound port when running."""

        return self._port


@contextmanager
def metrics_server(port: int, meters: CounterMeters | None = None) -> Iterator[MetricsServer]:
    """Context manager that runs :class:`MetricsServer` during the ``with`` block."""

    server = MetricsServer(meters or DEFAULT_METERS)
    server.start(port)
    try:
        yield server
    finally:
        server.stop()
