"""Lightweight PySide6 stub for headless CI environments."""
from __future__ import annotations

from types import ModuleType
from typing import Callable, Dict


class _BoundSignal:
    __slots__ = ("_slots",)

    def __init__(self) -> None:
        self._slots: list[Callable[..., None]] = []

    def connect(self, slot: Callable[..., None]) -> None:
        self._slots.append(slot)

    def emit(self, *args, **kwargs) -> None:
        for slot in list(self._slots):
            slot(*args, **kwargs)


class Signal:
    """Descriptor mimicking PySide6 ``Signal`` for tests."""

    def __init__(self, *signature: object) -> None:
        self._name: str | None = None
        self._signature = signature

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __get__(self, obj, owner=None):  # noqa: ANN001
        if obj is None:
            return self
        storage = obj.__dict__.setdefault("_qt_signals", {})
        if self._name not in storage:
            storage[self._name] = _BoundSignal()
        return storage[self._name]


class QObject:
    """Very small QObject stand-in used for presenter tests."""

    def __init__(self, parent: "QObject" | None = None) -> None:
        self._qt_parent = parent
        self._qt_signals: Dict[str, _BoundSignal] = {}


class QTimer(QObject):
    timeout = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active = False

    def start(self, _msec: int) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def isActive(self) -> bool:  # noqa: N802 - API compatibility
        return self._active


class _QtEnum:
    AlignCenter = 0x0004
    Horizontal = 1
    RightToLeft = 1
    LeftButton = 1


class _QtCoreModule(ModuleType):
    def __init__(self) -> None:
        super().__init__("PySide6.QtCore")
        self.QObject = QObject
        self.QTimer = QTimer
        self.Signal = Signal
        self.Qt = _QtEnum


class _QtGuiModule(ModuleType):
    def __init__(self) -> None:
        super().__init__("PySide6.QtGui")


class _QtWidgetsModule(ModuleType):
    def __init__(self) -> None:
        super().__init__("PySide6.QtWidgets")


def build_modules() -> Dict[str, ModuleType]:
    core = _QtCoreModule()
    gui = _QtGuiModule()
    widgets = _QtWidgetsModule()
    package = ModuleType("PySide6")
    package.QtCore = core  # type: ignore[attr-defined]
    package.QtGui = gui  # type: ignore[attr-defined]
    package.QtWidgets = widgets  # type: ignore[attr-defined]
    package.__all__ = ["QtCore", "QtGui", "QtWidgets"]
    return {
        "PySide6": package,
        "PySide6.QtCore": core,
        "PySide6.QtGui": gui,
        "PySide6.QtWidgets": widgets,
    }


__all__ = ["build_modules", "Signal", "QObject", "QTimer"]
