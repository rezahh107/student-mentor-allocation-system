"""اعتبارسنجی انتخاب تجزیه‌گر XML در اسکریپت درگاه پوشش."""
from __future__ import annotations

import importlib

import builtins
import pytest


def test_coverage_gate_prefers_defusedxml() -> None:
    """در دسترس بودن defusedxml باید به انتخاب آن منجر شود."""

    import scripts.coverage_gate as coverage_gate

    if coverage_gate.SAFE_XML_BACKEND != "defusedxml":
        pytest.skip("defusedxml نصب نشده است")

    assert coverage_gate.SAFE_XML_BACKEND == "defusedxml"


def test_coverage_gate_stdlib_fallback_logs_notice(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """در نبود defusedxml باید پیام هشدار فارسی چاپ شود."""

    import scripts.coverage_gate as coverage_gate

    original_import = builtins.__import__

    def _fake_import(name: str, globals: object | None = None, locals: object | None = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name.startswith("defusedxml"):
            raise ImportError("simulated missing defusedxml")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    capsys.readouterr()
    module = importlib.reload(coverage_gate)
    captured = capsys.readouterr()
    assert module.SAFE_XML_BACKEND == "stdlib"
    assert "SEC_SAFE_XML_FALLBACK" in captured.err

    monkeypatch.setattr(builtins, "__import__", original_import)
    importlib.reload(module)
