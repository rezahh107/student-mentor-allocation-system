from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Mapping

import httpx


class TestClient:
    """Minimal Starlette/FastAPI compatible test client built on httpx."""

    __test__ = False  # prevent pytest from collecting this helper as a test case

    def __init__(
        self,
        app: Any,
        *,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        transport_options: Mapping[str, Any] | None = None,
        **client_options: Any,
    ) -> None:
        self._transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=raise_server_exceptions,
            **(transport_options or {}),
        )
        self._client = httpx.AsyncClient(
            transport=self._transport,
            base_url=base_url,
            **client_options,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return asyncio.run(self._client.request(method, url, **kwargs))

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        asyncio.run(self._client.aclose())

    def __enter__(self) -> "TestClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        self.close()


@contextlib.contextmanager
def create_test_client(app: Any, **options: Any):
    client = TestClient(app, **options)
    try:
        yield client
    finally:
        client.close()
