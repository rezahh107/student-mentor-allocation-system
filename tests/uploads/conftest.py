from __future__ import annotations

import os
from datetime import datetime

import asyncio
import uuid
import httpx
import pytest
from fakeredis import FakeStrictRedis
from prometheus_client import CollectorRegistry

from phase2_uploads.app import create_app
from phase2_uploads.clock import FrozenClock, BAKU_TZ
from phase2_uploads.config import UploadsConfig
from phase2_uploads.repository import create_sqlite_repository


@pytest.fixture
def redis_client():
    client = FakeStrictRedis()
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture
def uploads_config(tmp_path) -> UploadsConfig:
    base_dir = tmp_path / "uploads"
    config = UploadsConfig.from_dict(
        {
            "base_dir": base_dir,
            "storage_dir": base_dir / "storage",
            "manifest_dir": base_dir / "manifests",
            "metrics_token": "secret-token",
            "namespace": "test-namespace",
        }
    )
    config.ensure_directories()
    return config


@pytest.fixture
def registry() -> CollectorRegistry:
    return CollectorRegistry()


@pytest.fixture
def clock() -> FrozenClock:
    frozen = datetime(2023, 9, 1, 8, 0, tzinfo=BAKU_TZ)
    return FrozenClock(fixed=frozen)


@pytest.fixture
def uploads_app(uploads_config, redis_client, registry, clock):
    repo_path = uploads_config.base_dir / "uploads.db"
    repository = create_sqlite_repository(str(repo_path))
    app = create_app(
        config=uploads_config,
        repository=repository,
        redis_client=redis_client,
        clock=clock,
        registry=registry,
    )
    transport = httpx.ASGITransport(app=app)

    class SyncClient:
        def __init__(self) -> None:
            self.app = app
            self._client = httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            )

        def request(self, method: str, url: str, **kwargs):
            data = kwargs.pop("data", None)
            files = kwargs.pop("files", None)
            headers = kwargs.pop("headers", {})
            content = kwargs.pop("content", None)
            if files is not None:
                body, boundary = self._encode_multipart(data or {}, files)
                headers = {
                    **headers,
                    "content-type": f"multipart/form-data; boundary={boundary}",
                    "content-length": str(len(body)),
                }
                data = None
                content = body
            return asyncio.run(
                self._client.request(
                    method,
                    url,
                    data=data,
                    content=content,
                    headers=headers,
                    **kwargs,
                )
            )

        def get(self, url: str, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url: str, **kwargs):
            return self.request("POST", url, **kwargs)

        def _encode_multipart(self, data, files):
            boundary = f"----uploads{uuid.uuid4().hex}"
            segments: list[bytes] = []
            for key, value in (data or {}).items():
                segment = (
                    f"--{boundary}\r\n"
                    f"Content-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                    f"{value}\r\n"
                ).encode("utf-8")
                segments.append(segment)
            for key, file_info in files.items():
                filename, content, *rest = file_info
                content_type = rest[0] if rest else "application/octet-stream"
                if isinstance(content, str):
                    content = content.encode("utf-8")
                header = (
                    f"--{boundary}\r\n"
                    f"Content-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8")
                segments.append(header + content + b"\r\n")
            segments.append(f"--{boundary}--\r\n".encode("utf-8"))
            return b"".join(segments), boundary

        def close(self) -> None:
            asyncio.run(self._client.aclose())
            asyncio.run(transport.aclose())

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    with SyncClient() as client:
        yield client
    repository.drop_schema()


@pytest.fixture
def service(uploads_app):
    return uploads_app.app.state.upload_service
