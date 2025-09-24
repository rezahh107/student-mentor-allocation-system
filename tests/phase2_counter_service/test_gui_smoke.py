# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib


def test_operator_panel_headless(monkeypatch) -> None:
    panel = importlib.import_module("tools.gui.operator_panel")
    monkeypatch.setattr(panel, "tk", None)
    exit_code = panel.main([])
    assert exit_code == 0


def test_headless_observer_hooks_noop() -> None:
    panel = importlib.import_module("tools.gui.operator_panel")
    observer = panel.build_headless_observer()
    observer.on_chunk(1, 2, 3, 4)
    observer.on_warning("msg", {"kind": "prefix"})
    observer.on_conflict("counter", {"chunk": 5})
    assert True
