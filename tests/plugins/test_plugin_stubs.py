from __future__ import annotations

import importlib
import json
import sys

import pytest

from tooling.logging_utils import get_json_logger
from tooling.metrics import get_registry, get_retry_counter, reset_registry

class DummyGroup:
    def addoption(self, *names: str, **kwargs) -> None:
        return None


class DummyParser:
    def __init__(self) -> None:
        self.groups: dict[str, DummyGroup] = {}
        self.ini: dict[str, tuple[str, str | None]] = {}

    def getgroup(self, name: str) -> DummyGroup:
        return self.groups.setdefault(name, DummyGroup())

    def addini(self, name: str, help: str, default: str | None = None) -> None:
        self.ini[name] = (help, default)

    def parse(self, args: list[str]) -> dict[str, str]:
        it = iter(args)
        result: dict[str, str] = {}
        for token in it:
            if token in {"-n", "--numprocesses"}:
                result["numprocesses"] = next(it)
            elif token == "--timeout":
                result["timeout"] = next(it)
        return result


def test_xdist_stub_accepts_short_option():
    from tooling.plugins import xdist_stub, timeout_stub

    xdist_stub.STUB_ENABLED = True
    parser = DummyParser()
    try:
        xdist_stub.pytest_addoption(parser)
        timeout_stub.pytest_addoption(parser)
        options = parser.parse(["-n", "2", "--timeout", "1"])
        assert options["numprocesses"] == "2"
        assert options["timeout"] == "1"
    finally:
        importlib.reload(importlib.import_module("tooling.plugins.xdist_stub"))


def test_stub_bails_when_real_plugin_present(monkeypatch):
    fake_module = type(sys)("xdist.plugin")
    fake_module.pytest_addoption = lambda parser: None
    monkeypatch.setitem(sys.modules, "xdist.plugin", fake_module)
    importlib.reload(importlib.import_module("tooling.plugins.xdist_stub"))
    from tooling.plugins import xdist_stub

    assert not xdist_stub.STUB_ENABLED
    monkeypatch.delitem(sys.modules, "tooling.plugins.xdist_stub")
    monkeypatch.delitem(sys.modules, "xdist.plugin")
    importlib.invalidate_caches()
    importlib.reload(importlib.import_module("tooling.plugins.xdist_stub"))


def test_logs_mask_pii(capsys: pytest.CaptureFixture[str]) -> None:
    logger = get_json_logger("pii", correlation_id="rid")
    logger.info("09123456789", extra={"mobile": "09123456789"})
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())
    assert payload["message"] == "0912****789"
    assert payload["mobile"] == "0912****789"
    assert payload["correlation_id"] == "rid"


def test_prom_registry_is_reset(metrics_registry) -> None:
    counter = get_retry_counter()
    counter.labels(operation="check", result="success").inc()
    assert list(metrics_registry.collect())
    reset_registry()
    assert list(get_registry().collect()) == []
