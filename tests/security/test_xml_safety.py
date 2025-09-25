"""تست‌های واحد برای اطمینان از پارس ایمن XML."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any, Dict

import pytest


@pytest.fixture(autouse=True)
def reset_module_cache() -> None:
    """حذف ماژول جهت بارگذاری مجدد در هر تست."""

    sys.modules.pop("scripts.check_coverage", None)


def test_defusedxml_not_installed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """تست رفتار در صورت عدم نصب defusedxml."""

    import scripts.check_coverage as coverage

    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name.startswith("defusedxml"):
            raise ImportError("No module named 'defusedxml'")
        return original_import(name, package)

    monkeypatch.setattr(coverage.importlib, "import_module", fake_import)
    result = coverage.parse_xml_safely("<root></root>")
    captured = capsys.readouterr()

    assert result is not None
    assert result["tag"] == "root"
    assert "defusedxml در دسترس نیست" in captured.err


def test_malicious_xml_blocked(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """تست مسدودسازی XML مخرب."""

    class FakeException(Exception):
        pass

    class FakeParser(SimpleNamespace):
        @staticmethod
        def fromstring(_: str) -> Dict[str, Any]:
            raise FakeException("محتوای مخرب")

    def fake_loader():
        return FakeParser, (FakeException,), True

    import scripts.check_coverage as coverage

    monkeypatch.setattr(coverage, "_load_parser", fake_loader)
    malicious_xml = "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><foo>&xxe;</foo>"
    result = coverage.parse_xml_safely(malicious_xml)
    captured = capsys.readouterr()

    assert result is None
    assert "XML مخرب" in captured.err


def test_fallback_rejects_dangerous_content(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """بررسی این‌که جایگزین ElementTree محتوای خطرناک را رد کند."""

    import scripts.check_coverage as coverage

    def fake_loader():
        return coverage.ET, (coverage.ET.ParseError,), False

    monkeypatch.setattr(coverage, "_load_parser", fake_loader)
    malicious_xml = "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><foo>&xxe;</foo>"
    result = coverage.parse_xml_safely(malicious_xml)
    captured = capsys.readouterr()

    assert result is None
    assert "XML حاوی ساختار خطرناک" in captured.err
