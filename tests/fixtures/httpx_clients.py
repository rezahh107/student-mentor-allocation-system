from __future__ import annotations

import httpx
import pytest


class ASGITransportCache:
    """Cache ASGI transports for re-use across tests."""

    def __init__(self) -> None:
        self._transports: dict[int, httpx.ASGITransport] = {}

    def acquire(self, app) -> httpx.ASGITransport:
        key = id(app)
        transport = self._transports.get(key)
        if transport is None:
            transport = httpx.ASGITransport(app=app, lifespan="auto")
            self._transports[key] = transport
        return transport

    def close_all(self) -> None:
        for transport in self._transports.values():
            transport.close()
        self._transports.clear()


@pytest.fixture(scope="session")
def asgi_transport_cache() -> ASGITransportCache:
    cache = ASGITransportCache()
    yield cache
    cache.close_all()


@pytest.fixture()
def httpx_client_factory(asgi_transport_cache: ASGITransportCache):
    clients: list[httpx.Client] = []

    def _factory(app) -> httpx.Client:
        transport = asgi_transport_cache.acquire(app)
        client = httpx.Client(transport=transport, base_url="http://testserver")
        clients.append(client)
        return client

    yield _factory

    for client in clients:
        client.close()
