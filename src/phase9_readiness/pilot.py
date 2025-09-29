from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable, Iterator

from src.reliability.clock import Clock


@dataclass(frozen=True)
class PilotStreamStats:
    """Summarised metrics for a streamed pilot dataset."""

    rows: int
    bytes: int
    elapsed_seconds: float
    checksum: str
    path: Path


class StreamingPilotMeter:
    """Stream a pilot dataset while tracking metrics without buffering the payload."""

    def __init__(
        self,
        *,
        source: Iterable[bytes] | Callable[[], Iterable[bytes]],
        clock: Clock,
        tmp_root: Path,
        chunk_hint: int = 65536,
    ) -> None:
        self._source = source
        self._clock = clock
        self._tmp_root = tmp_root
        self._chunk_hint = max(1024, int(chunk_hint))
        self._chunk_sizes: list[int] = []
        self._stats: PilotStreamStats | None = None
        self._spooled_path: Path | None = None
        self._prepared: bool = False

    def prepare(self) -> PilotStreamStats:
        if self._prepared:
            assert self._stats is not None
            return self._stats
        self._tmp_root.mkdir(parents=True, exist_ok=True)
        self._chunk_sizes.clear()
        digest = sha256()
        rows = 0
        bytes_total = 0
        leftover = b""

        def _spool() -> None:
            nonlocal rows, bytes_total, leftover
            iterator = self._resolve_source()
            with self._create_named_file() as fp:
                for raw_chunk in iterator:
                    chunk = self._normalise_chunk(raw_chunk)
                    if not chunk:
                        continue
                    fp.write(chunk)
                    self._chunk_sizes.append(len(chunk))
                    digest.update(chunk)
                    bytes_total += len(chunk)
                    buffer = leftover + chunk
                    pieces = buffer.split(b"\n")
                    rows += max(0, len(pieces) - 1)
                    leftover = pieces[-1] if buffer and not buffer.endswith(b"\n") else b""
                if leftover:
                    rows += 1
                    leftover = b""
                fp.flush()
                os.fsync(fp.fileno())
                self._spooled_path = Path(fp.name)

        _, elapsed = self._clock.measure(_spool)
        checksum = digest.hexdigest()
        path = self._spooled_path
        if path is None:
            raise RuntimeError("StreamingPilotMeter failed to create spool file.")
        self._stats = PilotStreamStats(
            rows=rows,
            bytes=bytes_total,
            elapsed_seconds=elapsed,
            checksum=checksum,
            path=path,
        )
        self._prepared = True
        return self._stats

    def stream(self) -> Iterator[bytes]:
        stats = self.prepare()
        if self._spooled_path is None:
            raise RuntimeError("StreamingPilotMeter missing spool file during stream().")
        if not self._chunk_sizes:
            return iter(())
        return self._iter_from_spool(stats.path)

    def cleanup(self) -> None:
        path = self._spooled_path
        if path and path.exists():
            path.unlink(missing_ok=True)
        self._chunk_sizes.clear()
        self._prepared = False
        self._stats = None
        self._spooled_path = None

    def _iter_from_spool(self, path: Path) -> Iterator[bytes]:
        with path.open("rb") as fp:
            for size in self._chunk_sizes:
                if size <= 0:
                    continue
                chunk = fp.read(size)
                if not chunk:
                    break
                yield chunk

    def _resolve_source(self) -> Iterator[bytes]:
        candidate = self._source() if callable(self._source) else self._source
        return iter(candidate)

    def _create_named_file(self):
        filename = f"pilot_{uuid.uuid4().hex}.dat"
        return open(self._tmp_root / filename, "wb", buffering=self._chunk_hint)

    @staticmethod
    def _normalise_chunk(chunk: bytes | bytearray | memoryview) -> bytes:
        if isinstance(chunk, (bytes, bytearray)):
            data = bytes(chunk)
        elif isinstance(chunk, memoryview):
            data = chunk.tobytes()
        else:
            data = bytes(str(chunk), encoding="utf-8")
        return data


__all__ = ["StreamingPilotMeter", "PilotStreamStats"]
