from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from sma.phase6_import_to_sabt.sanitization import sanitize_text
from sma.phase6_import_to_sabt.xlsx.retry import retry_with_backoff


@contextmanager
def atomic_write(
    path: Path,
    mode: str = "wb",
    *,
    attempts: int = 3,
    backoff_seed: str = "fsync",
    on_retry: Callable[[int], None] | None = None,
    metrics=None,
    format_label: str = "unknown",
    sleeper: Callable[[float], None] | None = None,
):
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, mode) as handle:
        try:
            yield handle
            handle.flush()
            retry_with_backoff(
                lambda attempt: _fsync(handle),
                attempts=attempts,
                base_delay=0.01,
                seed=f"{backoff_seed}_fsync",
                metrics=metrics,
                format_label=format_label,
                sleeper=sleeper,
                on_retry=on_retry,
            )
        except Exception:
            handle.close()
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            raise
    os.replace(temp_path, path)


def _fsync(handle) -> None:
    os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_header(value: str) -> str:
    return sanitize_text(value).lower()


def dumps_deterministic(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    with atomic_write(path, mode="w", backoff_seed="manifest") as handle:
        handle.write(dumps_deterministic(payload))


def cleanup_partials(directory: Path) -> None:
    if not directory.exists():
        return
    for item in directory.glob("*.part"):
        try:
            item.unlink()
        except FileNotFoundError:
            continue


def ensure_max_size(path: Path, max_bytes: int) -> None:
    if path.stat().st_size > max_bytes:
        raise ValueError("UPLOAD_TOO_LARGE")


def iter_chunks(items: Iterable[Any], chunk_size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) == chunk_size:
            yield batch
            batch = []
    if batch:
        yield batch
