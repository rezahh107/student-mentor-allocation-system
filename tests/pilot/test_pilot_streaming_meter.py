from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Iterator

from zoneinfo import ZoneInfo

from sma.phase9_readiness.pilot import StreamingPilotMeter
from sma.reliability.clock import Clock


class CountingIterable:
    def __init__(self, count: int) -> None:
        self.count = count
        self.iterations = 0

    def __iter__(self) -> Iterator[bytes]:
        self.iterations += 1
        for index in range(self.count):
            yield f"row-{index:05d}\n".encode("utf-8")


def test_streaming_no_buffer_blowup(tmp_path) -> None:
    clock = Clock(ZoneInfo("Asia/Tehran"), lambda: datetime(2024, 3, 20, 10, tzinfo=ZoneInfo("UTC")))
    source = CountingIterable(2000)
    meter = StreamingPilotMeter(source=source, clock=clock, tmp_root=tmp_path / "spool")
    stats = meter.prepare()
    assert source.iterations == 1
    expected_checksum = sha256()
    total_bytes = 0
    for index in range(source.count):
        payload = f"row-{index:05d}\n".encode("utf-8")
        expected_checksum.update(payload)
        total_bytes += len(payload)
    assert stats.bytes == total_bytes
    assert stats.rows == source.count
    assert stats.checksum == expected_checksum.hexdigest()
    assert stats.path.exists()

    digest_first = sha256()
    for chunk in meter.stream():
        digest_first.update(chunk)
    assert digest_first.hexdigest() == stats.checksum

    digest_second = sha256()
    for chunk in meter.stream():
        digest_second.update(chunk)
    assert digest_second.hexdigest() == stats.checksum

    meter.cleanup()
    assert not stats.path.exists()
