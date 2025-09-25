from __future__ import annotations

from dataclasses import dataclass

from src.ui.trace_viewer import TraceViewerApp, TraceViewerRow


class FakeWidget:
    def __init__(self, master: "FakeWidget" | None = None, **kwargs) -> None:
        self.master = master
        self.children: list[FakeWidget] = []
        if master is not None:
            master.children.append(self)
        self._value = ""
        self.kwargs = kwargs

    def pack(self, **_kwargs) -> None:
        return None

    def bind(self, *_args, **_kwargs) -> None:
        return None

    def configure(self, **_kwargs) -> None:
        return None


class FakeEntry(FakeWidget):
    def get(self) -> str:
        return self._value

    def insert(self, index: int, value: str) -> None:
        prefix = self._value[:index]
        suffix = self._value[index:]
        self._value = prefix + value + suffix

    def delete(self, _start: int, _end: str | None = None) -> None:
        self._value = ""


class FakeListbox(FakeWidget):
    def __init__(self, master: FakeWidget | None = None, **kwargs) -> None:
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

    def yview(self, *_args, **_kwargs) -> None:
        return None


class FakeText(FakeWidget):
    def __init__(self, master: FakeWidget | None = None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.content = ""

    def delete(self, _start: str, _end: str) -> None:
        self.content = ""

    def insert(self, _index: str, value: str) -> None:
        self.content += value


class FakeScrollbar(FakeWidget):
    def set(self, *_args) -> None:
        return None


class FakeFrame(FakeWidget):
    pass


class FakeLabel(FakeWidget):
    pass


class FakeTkModule:
    END = "end"

    class Tk(FakeWidget):
        def __init__(self) -> None:
            super().__init__(None)
            self._after_calls: list[tuple[int, callable]] = []

        def title(self, *_args) -> None:
            return None

        def geometry(self, *_args) -> None:
            return None

        def after(self, _delay: int, callback) -> int:
            self._after_calls.append((_delay, callback))
            callback()
            return len(self._after_calls)

        def bind(self, *_args, **_kwargs) -> None:
            return None

        def destroy(self) -> None:
            return None

        def mainloop(self) -> None:
            return None

    Frame = FakeFrame
    Label = FakeLabel
    Entry = FakeEntry
    Listbox = FakeListbox
    Scrollbar = FakeScrollbar
    Text = FakeText


def test_trace_viewer_filters_and_renders() -> None:
    module = FakeTkModule()
    rows = [
        TraceViewerRow(
            student_index=0,
            mentor_id="101",
            mentor_type="NORMAL",
            passed=True,
            occupancy_ratio=0.25,
            current_load=1,
            trace=[{"code": "GENDER_MATCH", "passed": True, "details": {}}],
        ),
        TraceViewerRow(
            student_index=1,
            mentor_id="202",
            mentor_type="SCHOOL",
            passed=False,
            occupancy_ratio=None,
            current_load=None,
            trace=[{"code": "GROUP_ALLOWED", "passed": False, "details": {"group_code": "X"}}],
        ),
    ]
    rows[0].student_group = "A"
    rows[0].student_center = "0"
    rows[0].is_selected = True
    rows[1].student_group = "B"
    rows[1].student_center = "1"
    root = module.Tk()
    app = TraceViewerApp(root, rows, tk_module=module)
    assert len(app._visible_rows) == 2
    assert app.listbox.items[0].startswith("★")

    app.group_entry.delete(0, module.END)
    app.group_entry.insert(0, "B")
    app._on_filter_change(None)
    assert len(app._visible_rows) == 1
    app._show_entry(0)
    assert "GROUP_ALLOWED" in app.trace_text.content
