from __future__ import annotations

from sma.phase6_import_to_sabt.xlsx.constants import DEFAULT_CHUNK_SIZE


def test_streaming_memory_budget():
    assert DEFAULT_CHUNK_SIZE == 50_000
