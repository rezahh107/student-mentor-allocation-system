from __future__ import annotations

import json
from pathlib import Path

from sma.phase2_counter_service.logging_utils import atomic_debug_dump


def test_atomic_write(tmp_path: Path) -> None:
    destination = tmp_path / "debug.json"
    payload = {"status": "ok", "counter": "023730001"}
    written = atomic_debug_dump(destination, payload)
    assert written.exists()
    assert not destination.with_suffix(".json.part").exists()
    data = json.loads(destination.read_text("utf-8"))
    assert data == payload
