"""Streaming SHA-256 helpers."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Iterable


_CHUNK_SIZE = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
        digest.update(chunk)
    return digest.hexdigest()


__all__ = ["sha256_bytes", "sha256_file", "sha256_stream"]
