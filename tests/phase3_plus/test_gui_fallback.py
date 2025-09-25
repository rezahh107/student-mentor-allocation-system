from __future__ import annotations

from types import MethodType

from src.ui.trace_index import TraceFilterIndex
from src.ui.trace_viewer import TraceViewerApp, TraceViewerRow, TraceViewerStorageWriter


class _FakeWidget:
    def __init__(self, master: "_FakeWidget | None" = None, **kwargs) -> None:
        self.master = master
        self.children: list[_FakeWidget] = []
        if master is not None:
            master.children.append(self)
        self.kwargs = kwargs

    def pack(self, **_kwargs) -> None:  # pragma: no cover - geometry noop
        return None

    def bind(self, *_args, **_kwargs) -> None:  # pragma: no cover - event noop
        return None

    def configure(self, **_kwargs) -> None:  # pragma: no cover - configuration noop
        return None


class _FakeEntry(_FakeWidget):
    def __init__(self, master: "_FakeWidget | None" = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.value = ""

    def get(self) -> str:
        return self.value

    def insert(self, index: int, value: str) -> None:
        del index  # pragma: no cover - unused in fake
        self.value += value

    def delete(self, _start: int, _end: str | None = None) -> None:
        self.value = ""


class _FakeListbox(_FakeWidget):
    def __init__(self, master: "_FakeWidget | None" = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.items: list[str] = []
        self.selection: list[int] = []

    def delete(self, _start: int, _end: str | None = None) -> None:
        self.items.clear()

    def insert(self, _index: str, value: str) -> None:
        self.items.append(value)

    def selection_set(self, index: int) -> None:
        self.selection = [index]

    def curselection(self) -> tuple[int, ...]:
        return tuple(self.selection)

    def yview(self, *_args, **_kwargs) -> None:  # pragma: no cover - scroll noop
        return None


class _FakeScrollbar(_FakeWidget):
    def set(self, *_args) -> None:  # pragma: no cover - noop
        return None


class _FakeText(_FakeWidget):
    def __init__(self, master: "_FakeWidget | None" = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.content = ""

    def delete(self, _start: str, _end: str) -> None:
        self.content = ""

    def insert(self, _index: str, value: str) -> None:
        self.content += value


class _FakeButton(_FakeWidget):
    def __init__(self, master: "_FakeWidget | None" = None, command=None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.command = command

    def invoke(self) -> None:
        if self.command:
            self.command()


class _FakeFrame(_FakeWidget):
    pass


class _FakeLabel(_FakeWidget):
    pass


class _FakeTkModule:
    END = "end"

    class Tk(_FakeWidget):
        def __init__(self) -> None:
            super().__init__(None)
            self._after_calls: list[tuple[int, callable]] = []

        def title(self, *_args) -> None:  # pragma: no cover - noop
            return None

        def geometry(self, *_args) -> None:  # pragma: no cover - noop
            return None

        def after(self, _delay: int, callback) -> int:
            self._after_calls.append((_delay, callback))
            callback()
            return len(self._after_calls)

        def bind(self, *_args, **_kwargs) -> None:  # pragma: no cover - noop
            return None

        def destroy(self) -> None:  # pragma: no cover - noop
            return None

        def mainloop(self) -> None:  # pragma: no cover - noop
            return None

    Frame = _FakeFrame
    Label = _FakeLabel
    Entry = _FakeEntry
    Listbox = _FakeListbox
    Scrollbar = _FakeScrollbar
    Text = _FakeText
    Button = _FakeButton


def _row(index: int) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=index,
        mentor_id=f"M{index}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    if index % 2 == 0:
        row.student_group = "G1"
        row.student_center = "C1"
    else:
        row.student_group = "G2"
        row.student_center = "C0"
    return row


def test_listbox_fallback_pages_in_fixed_batches() -> None:
    module = _FakeTkModule()
    writer = TraceViewerStorageWriter()
    total_rows = 120
    for idx in range(total_rows):
        writer.append_rows([_row(idx)])
    storage = writer.finalize()

    calls: list[int] = []
    original_get_row = storage.get_row

    def _logged_get_row(self, index: int) -> TraceViewerRow:
        calls.append(index)
        return original_get_row(index)

    storage.get_row = MethodType(_logged_get_row, storage)

    root = module.Tk()
    try:
        index = TraceFilterIndex(storage)
        app = TraceViewerApp(
            root,
            storage,
            tk_module=module,
            page_size=25,
            initial_page=1,
            index=index,
        )
        assert len(app.listbox.items) == 25
        assert len(app._page_rows) == 25

        app.group_entry.insert(0, "G1")
        app.center_entry.insert(0, "C1")
        app._on_filter_change(None)
        assert app._filtered_count == 60
        assert len(app.listbox.items) == 25
        assert len(app._page_rows) == 25

        before_next = len(calls)
        app._load_next_page()
        after_next = len(calls)
        assert 0 < after_next - before_next <= 25
        assert len(app.listbox.items) == 25 or len(app._page_rows) < 25
    finally:
        root.destroy()
        storage.cleanup()
