from __future__ import annotations

import importlib
import types
import urllib.error
from collections import defaultdict

import pytest

from scripts import server_check as server_check_module


class DummyResponse:
    def __init__(self, code: int) -> None:
        self._code = code

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - standard context exit
        return None

    def getcode(self) -> int:
        return self._code


def _reload(monkeypatch: pytest.MonkeyPatch, **env: str) -> types.ModuleType:
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return importlib.reload(server_check_module)


@pytest.mark.ci
def test_hit_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _reload(monkeypatch)
    attempt_log: list[int] = []

    def _fake_urlopen(request, timeout):
        attempt_log.append(timeout)
        if len(attempt_log) < 3:
            raise urllib.error.URLError("timeout")
        return DummyResponse(200)

    sleeps: list[float] = []
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    ok = module._hit("/healthz", [200])

    out = capsys.readouterr().out
    assert ok is True
    assert out.count("❌ /healthz -> None") == 2
    assert "✅ /healthz -> 200" in out
    assert sleeps == [0.3, 0.3]


@pytest.mark.ci
def test_hit_handles_http_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _reload(monkeypatch)

    def _fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    ok = module._hit("/metrics", [403])
    out = capsys.readouterr().out
    assert ok is True
    assert "✅ /metrics -> 403" in out


@pytest.mark.ci
def test_hit_failure_reports_last_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = _reload(monkeypatch)

    class Boom(RuntimeError):
        pass

    def _boom(request, timeout):
        raise Boom("شبکه در دسترس نیست")

    monkeypatch.setattr(module.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    ok = module._hit("/docs", [200])
    out = capsys.readouterr().out
    assert ok is False
    assert "❌ /docs error: شبکه در دسترس نیست" in out


@pytest.mark.ci
def test_main_respects_public_docs_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload(
        monkeypatch,
        REQUIRE_PUBLIC_DOCS="1",
        METRICS_ENDPOINT_ENABLED="true",
    )

    calls: defaultdict[str, list[tuple[tuple[int, ...], dict[str, str] | None]]] = defaultdict(list)

    def _fake_hit(path, expect_codes, headers=None, attempts=3, backoff=0.3):
        calls[path].append((tuple(expect_codes), headers))
        return True

    exits: list[int] = []
    monkeypatch.setattr(module, "_hit", _fake_hit)
    monkeypatch.setattr(module.sys, "exit", lambda code: exits.append(code))

    module.main()

    assert exits == [0]
    assert calls["/docs"][0][0] == (200,)
    assert calls["/openapi.json"][0][0] == (200,)
    assert calls["/redoc"][0][0] == (200,)
    metrics_calls = calls["/metrics"]
    assert metrics_calls == [((200,), None)]


@pytest.mark.ci
def test_main_skips_metrics_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload(monkeypatch, REQUIRE_PUBLIC_DOCS="0", METRICS_ENDPOINT_ENABLED="")
    metrics_invocations: list[tuple[tuple[int, ...], dict[str, str] | None]] = []

    def _fake_hit(path, expect_codes, headers=None, attempts=3, backoff=0.3):
        if path == "/metrics":
            metrics_invocations.append((tuple(expect_codes), headers))
        return True

    exits: list[int] = []
    monkeypatch.setattr(module, "_hit", _fake_hit)
    monkeypatch.setattr(module.sys, "exit", lambda code: exits.append(code))

    module.main()

    assert exits == [0]
    assert metrics_invocations == []


@pytest.mark.ci
def test_main_checks_metrics_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload(monkeypatch, REQUIRE_PUBLIC_DOCS="0", METRICS_ENDPOINT_ENABLED="true")
    metrics_invocations: list[tuple[tuple[int, ...], dict[str, str] | None]] = []

    def _fake_hit(path, expect_codes, headers=None, attempts=3, backoff=0.3):
        if path == "/metrics":
            metrics_invocations.append((tuple(expect_codes), headers))
        return True

    exits: list[int] = []
    monkeypatch.setattr(module, "_hit", _fake_hit)
    monkeypatch.setattr(module.sys, "exit", lambda code: exits.append(code))

    module.main()

    assert exits == [0]
    assert metrics_invocations == [((200,), None)]
