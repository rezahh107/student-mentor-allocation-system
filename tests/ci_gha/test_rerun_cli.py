from __future__ import annotations

import json
from typing import Any, List

import pytest

from tools import gha_rerun


class _FakeResponse:
    def __init__(self, status: int, payload: Any | None = None) -> None:
        self._status = status
        self._payload = payload or {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_rerun_happy_path(clean_state, retry_call, monkeypatch, capsys):
    queue: List[Any] = [
        _FakeResponse(200, {"workflow_runs": [{"id": 42, "html_url": "https://example/run/42"}]}),
        _FakeResponse(201, {"message": "https://example/run/42"}),
    ]

    def fake_urlopen(request, timeout=30):  # pragma: no cover - called indirectly
        assert queue, "درخواست بیش از انتظار بود"
        return queue.pop(0)

    monkeypatch.setattr(gha_rerun.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "tkn")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/example")

    def _invoke() -> int:
        return gha_rerun.run(["--workflow", "ci.yml", "--branch", "main"])

    rc = retry_call(_invoke)
    assert rc == 0, "اجرای بازاجرا باید موفق شود"

    out = capsys.readouterr().out
    assert "شناسه اجرا: 42" in out, f"خلاصه فارسی یافت نشد؛ خروجی: {out}"
    assert "وضعیت: 201" in out, f"کد وضعیت باید درج شود؛ خروجی: {out}"


def test_rerun_retries_on_server_error(clean_state, retry_call, monkeypatch, capsys):
    class _Boom(gha_rerun.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("http://example", 502, "bad gateway", {}, None)

        def read(self) -> bytes:  # pragma: no cover - ensures message available
            return b"bad gateway"

    responses: List[Any] = [
        _Boom(),
        _FakeResponse(200, {"workflow_runs": [{"id": 11, "html_url": "https://example/run/11"}]}),
        _FakeResponse(201, {"message": "https://example/run/11"}),
    ]

    def fake_urlopen(request, timeout=30):  # pragma: no cover
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(gha_rerun.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "tkn")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/example")

    rc = retry_call(lambda: gha_rerun.run(["--workflow", "ci.yml", "--branch", "main"]))
    assert rc == 0, "پس از خطای موقت باید موفق شود"
    out = capsys.readouterr().out
    assert "شناسه اجرا: 11" in out, f"خروجی نهایی اشتباه بود: {out}"


def test_rerun_unauthorized_failure(clean_state, retry_call, monkeypatch):
    class _Unauthorized(gha_rerun.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("http://example", 401, "unauthorized", {}, None)

        def read(self) -> bytes:  # pragma: no cover
            return b"no auth"

    def fake_urlopen(request, timeout=30):  # pragma: no cover
        raise _Unauthorized()

    monkeypatch.setattr(gha_rerun.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "bad")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/example")

    with pytest.raises(gha_rerun.RerunError) as exc:
        retry_call(lambda: gha_rerun.run(["--workflow", "ci.yml", "--branch", "main"]))

    assert "RERUN_AUTH_FAILED" in str(exc.value), f"کد خطا باید مشخص باشد: {exc.value}"


def test_rerun_not_found_failure(clean_state, retry_call, monkeypatch):
    class _Missing(gha_rerun.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__("http://example", 404, "not found", {}, None)

        def read(self) -> bytes:  # pragma: no cover
            return b"missing"

    def fake_urlopen(request, timeout=30):  # pragma: no cover
        raise _Missing()

    monkeypatch.setattr(gha_rerun.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "bad")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octocat/example")

    with pytest.raises(gha_rerun.RerunError) as exc:
        retry_call(lambda: gha_rerun.run(["--workflow", "ci.yml", "--branch", "main"]))

    assert "RERUN_NOT_FOUND" in str(exc.value), f"باید خطای نبودن منبع برگردد: {exc.value}"
