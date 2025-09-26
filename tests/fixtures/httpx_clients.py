from __future__ import annotations

import asyncio
import json
from typing import Any, Iterator

import pytest

try:  # pragma: no cover - optional dependency for richer HTTP clients
    import httpx
except Exception:  # pragma: no cover - allow running without httpx installed
    httpx = None  # type: ignore[assignment]

if httpx is not None:
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
    def asgi_transport_cache() -> Iterator[ASGITransportCache]:
        cache = ASGITransportCache()
        try:
            yield cache
        finally:
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
else:  # pragma: no cover - fallback when httpx (and Starlette) are unavailable
    class MinimalResponse:
        """Simplified HTTP response wrapper used in fallback client."""

        def __init__(self, status_code: int, headers: list[tuple[bytes, bytes]], body: bytes) -> None:
            self.status_code = status_code
            self._body = body
            self.headers = {
                key.decode("latin-1"): value.decode("latin-1") for key, value in headers
            }

        def json(self) -> Any:
            if not self._body:
                return None
            return json.loads(self._body.decode("utf-8"))

        @property
        def content(self) -> bytes:
            return self._body

        @property
        def text(self) -> str:
            return self._body.decode("utf-8")


    class MinimalASGITestClient:
        """Synchronous ASGI client that doesn't rely on external libraries."""

        def __init__(self, app) -> None:
            self._app = app
            self.base_url = "http://testserver"

        def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            json_body: Any | None = None,
            data: bytes | None = None,
        ) -> MinimalResponse:
            raw_body = b""
            send_headers: dict[str, str] = {k.lower(): v for k, v in (headers or {}).items()}
            if json_body is not None:
                raw_body = json.dumps(json_body).encode("utf-8")
                send_headers.setdefault("content-type", "application/json; charset=utf-8")
            elif data is not None:
                raw_body = data
            send_headers.setdefault("host", "testserver")

            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": url,
                "raw_path": url.encode("utf-8"),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (key.encode("latin-1"), value.encode("latin-1")) for key, value in send_headers.items()
                ],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            }

            async def receive() -> dict[str, Any]:
                nonlocal raw_body
                if raw_body is None:
                    return {"type": "http.disconnect"}
                body = raw_body
                raw_body = None
                return {"type": "http.request", "body": body, "more_body": False}

            response_headers: list[tuple[bytes, bytes]] = []
            response_body = bytearray()
            status_code = 500

            async def send(message: dict[str, Any]) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = int(message["status"])
                    response_headers.extend(message.get("headers", []))
                elif message["type"] == "http.response.body":
                    response_body.extend(message.get("body", b""))

            async def app_call() -> MinimalResponse:
                await self._app(scope, receive, send)
                return MinimalResponse(status_code, response_headers, bytes(response_body))

            return asyncio.run(app_call())

        def get(self, url: str, *, headers: dict[str, str] | None = None) -> MinimalResponse:
            return self.request("GET", url, headers=headers)

        def post(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            json: Any | None = None,
            data: bytes | None = None,
        ) -> MinimalResponse:
            return self.request("POST", url, headers=headers, json_body=json, data=data)

        def close(self) -> None:
            return


    @pytest.fixture()
    def httpx_client_factory():
        clients: list[MinimalASGITestClient] = []

        def _factory(app) -> MinimalASGITestClient:
            client = MinimalASGITestClient(app)
            clients.append(client)
            return client

        yield _factory

        for client in clients:
            client.close()
