from __future__ import annotations

import json

from src.reliability.atomic import atomic_write_json


def test_atomic_manifest(tmp_path):
    destination = tmp_path / "manifest.json"
    payload = {"name": "demo", "port": 1234}
    atomic_write_json(destination, payload)

    assert destination.exists()
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert not destination.with_suffix(".json.part").exists()
