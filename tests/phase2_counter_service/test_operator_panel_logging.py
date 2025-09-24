# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import json
import logging
from types import SimpleNamespace
from typing import Callable, List, Tuple

import pytest

panel = importlib.import_module("tools.gui.operator_panel")


class FakeVar:
    def __init__(self) -> None:
        self._value: float | str | None = None

    def set(self, value: float | str) -> None:
        self._value = value

    def get(self) -> float | str | None:
        return self._value


class FakeListbox:
    def __init__(self) -> None:
        self.items: List[str] = []
        self._last_index: int | None = None

    def insert(self, index: object, value: str) -> None:
        self.items.append(value)

    def see(self, index: object) -> None:  # pragma: no cover - trivial tracking
        self._last_index = len(self.items) if self.items else None


class FakeWidget:
    def pack(self, *args, **kwargs) -> None:  # pragma: no cover - noop helper
        return None


class FakeRoot:
    def __init__(self) -> None:
        self.titles: List[str] = []
        self.after_calls: List[Tuple[int, Callable[[], None]]] = []
        self.protocols: dict[str, Callable[[], None]] = {}
        self.quit_called = False
        self.destroy_called = False

    def title(self, value: str) -> None:
        self.titles.append(value)

    def protocol(self, name: str, func: Callable[[], None]) -> None:
        self.protocols[name] = func

    def after(self, delay: int, callback: Callable[[], None]) -> None:
        self.after_calls.append((delay, callback))

    def quit(self) -> None:
        self.quit_called = True

    def destroy(self) -> None:
        self.destroy_called = True

    def mainloop(self) -> None:  # pragma: no cover - not used in headless test
        raise AssertionError("Mainloop should not be invoked in tests")


@pytest.fixture(autouse=True)
def _patch_tk(monkeypatch) -> None:
    monkeypatch.setattr(panel, "tk", SimpleNamespace(END="end"))


def test_operator_panel_logging_pipeline(monkeypatch) -> None:
    def fake_build_ui(self: "panel.OperatorPanel") -> None:
        self._progress_var = FakeVar()
        self._progress = FakeWidget()
        self._status_var = FakeVar()
        self._warnings = FakeListbox()

    monkeypatch.setattr(panel.OperatorPanel, "_build_ui", fake_build_ui)

    logger = logging.getLogger("phase2-test.panel")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    root = FakeRoot()
    operator = panel.OperatorPanel(root, logger=logger)

    assert sum(isinstance(h, panel.ObserverLogHandler) for h in logger.handlers) == 1
    assert root.after_calls

    operator.observer.on_chunk(1, 3, 1, 0)
    operator._process_events()
    status = operator._status_var.get()
    assert status is not None and "دسته 1" in status
    assert "اعمال 3" in status

    warning_payload = json.dumps({"پیام": "هشدار مهم", "جزئیات": {"کد": 1}})
    logger.warning(warning_payload)
    conflict_payload = json.dumps({"پیام": "conflict_resolved", "نوع": "prefix"})
    logger.warning(conflict_payload)
    operator._process_events()

    assert operator._warnings.items[-1] == "تعارض برطرف شد: prefix"
    assert "هشدار مهم" in operator._warnings.items[0]

    operator.shutdown()
    assert sum(isinstance(h, panel.ObserverLogHandler) for h in logger.handlers) == 0

    second = panel.OperatorPanel(FakeRoot(), logger=logger)
    assert sum(isinstance(h, panel.ObserverLogHandler) for h in logger.handlers) == 1
    second.shutdown()


def test_operator_panel_supports_multiple_panels(monkeypatch) -> None:
    def fake_build_ui(self: "panel.OperatorPanel") -> None:
        self._progress_var = FakeVar()
        self._progress = FakeWidget()
        self._status_var = FakeVar()
        self._warnings = FakeListbox()

    monkeypatch.setattr(panel.OperatorPanel, "_build_ui", fake_build_ui)

    logger = logging.getLogger("phase2-test.panel.multi")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.propagate = False

    first = panel.OperatorPanel(FakeRoot(), logger=logger)
    second = panel.OperatorPanel(FakeRoot(), logger=logger)

    handlers = [h for h in logger.handlers if isinstance(h, panel.ObserverLogHandler)]
    assert len(handlers) == 2
    assert len({h.lease_id for h in handlers}) == 2

    warning_payload = json.dumps({"پیام": "هشدار همزمان"})
    logger.warning(warning_payload)
    first._process_events()
    second._process_events()

    assert any("هشدار همزمان" in item for item in first._warnings.items)
    assert any("هشدار همزمان" in item for item in second._warnings.items)

    first.shutdown()
    remaining = [h for h in logger.handlers if isinstance(h, panel.ObserverLogHandler)]
    assert len(remaining) == 1
    assert remaining[0].lease_id == second._lease_id

    conflict_payload = json.dumps({"پیام": "conflict_resolved", "نوع": "prefix"})
    logger.warning(conflict_payload)
    second._process_events()

    assert any("تعارض" in item for item in second._warnings.items)

    second.shutdown()
    assert sum(isinstance(h, panel.ObserverLogHandler) for h in logger.handlers) == 0
