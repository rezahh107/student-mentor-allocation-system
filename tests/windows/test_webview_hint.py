import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from windows_launcher.launcher import LauncherError, WEBVIEW2_HINT, _PyWebviewBackend


@pytest.fixture(name="fake_webview")
def fixture_fake_webview(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    unique = uuid4().hex

    def _create_window(title: str, url: str, **kwargs) -> dict[str, object]:
        return {"title": title, "url": url, "kwargs": kwargs, "token": unique}

    def _start(func, debug: bool = False) -> None:  # pragma: no cover - invoked via backend.start
        raise RuntimeError("EdgeChromiumInitializationError: WebView2 runtime missing")

    module = SimpleNamespace(create_window=_create_window, start=_start, token=unique)
    monkeypatch.setitem(sys.modules, "webview", module)
    try:
        yield module
    finally:
        monkeypatch.delenv("FAKE_WEBVIEW", raising=False)
        monkeypatch.delitem(sys.modules, "webview", raising=False)


def test_webview_missing_runtime_hint(fake_webview: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_WEBVIEW", "0")
    backend = _PyWebviewBackend()
    backend.create_window("title", url="http://127.0.0.1", token=fake_webview.token)
    with pytest.raises(LauncherError) as excinfo:
        backend.start(None)
    error = excinfo.value
    assert error.code == "WEBVIEW2_MISSING", f"Unexpected code: {error.code}" \
        + f" context={error.context}"
    assert error.message == WEBVIEW2_HINT, f"Hint mismatch: {error.message}"
    assert "detail" in error.context, f"Missing detail context: {error.context}"
