from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import pytest

from sma.phase6_import_to_sabt.app.io_utils import write_atomic


def _retry(action: Callable[[], None], *, attempts: int = 3, base_delay: float = 0.0005) -> None:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            action()
            return
        except AssertionError as exc:
            errors.append(str(exc))
            if attempt == attempts:
                raise AssertionError("; ".join(errors))
            delay = base_delay * (2 ** (attempt - 1)) + (attempt * 0.0001)
            time.sleep(delay)


@pytest.fixture
def target_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "atomic.bin"
    yield file_path
    for leftover in tmp_path.iterdir():
        if leftover.is_file():
            leftover.unlink()


def test_write_atomic_replaces_file_safely(target_file: Path) -> None:
    first = b"primary payload"
    second = b"secondary payload with more bytes"

    write_atomic(target_file, first)
    context = {"attempt": 1, "path": str(target_file)}

    def _assert_first_write() -> None:
        assert target_file.exists(), f"Missing file after first write: {context}"
        assert target_file.read_bytes() == first, "Initial payload mismatch"

    _retry(_assert_first_write)

    write_atomic(target_file, second)
    context.update({"attempt": 2})

    def _assert_second_write() -> None:
        assert target_file.read_bytes() == second, f"Replacement payload mismatch: {context}"

    _retry(_assert_second_write)

    leftovers = list(target_file.parent.glob("*.part"))
    assert not leftovers, f"Temporary part files leaked: {leftovers}"
