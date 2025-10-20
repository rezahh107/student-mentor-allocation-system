"""Backup and restore helpers for exporter artifacts."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from .atomic import atomic_write
from .hashing import sha256_file

_BUFFER = 1024 * 1024


@dataclass(frozen=True)
class BackupEntry:
    name: str
    sha256: str
    size: int


@dataclass(frozen=True)
class BackupBundle:
    directory: Path
    manifest: Path
    entries: Sequence[BackupEntry]


@dataclass(frozen=True)
class RetentionDecision:
    path: Path
    action: str
    reason: str
    size: int
    age_days: int


@dataclass(frozen=True)
class RetentionPlan:
    decisions: Sequence[RetentionDecision]
    freed_bytes: int
    kept_bytes: int


class BackupManager:
    """Create deterministic backups with hash verification."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._clock = clock

    def backup(self, *, sources: Sequence[Path], destination: Path) -> BackupBundle:
        timestamp = self._clock().strftime("%Y%m%dT%H%M%SZ")
        target_dir = Path(destination) / timestamp
        target_dir.mkdir(parents=True, exist_ok=True)
        entries: list[BackupEntry] = []
        for source in sorted(sources, key=lambda p: p.name):
            source_path = Path(source)
            target_path = target_dir / source_path.name
            digest, size = _copy_with_hash(source_path, target_path)
            entries.append(BackupEntry(name=source_path.name, sha256=digest, size=size))
        manifest = target_dir / "manifest.json"
        payload = {
            "generated_at": timestamp,
            "entries": [entry.__dict__ for entry in entries],
        }
        atomic_write(manifest, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return BackupBundle(directory=target_dir, manifest=manifest, entries=entries)

    def restore(self, *, manifest: Path, destination: Path) -> None:
        manifest_data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        bundle_dir = Path(manifest).parent
        for entry in manifest_data.get("entries", []):
            name = entry["name"]
            sha = entry["sha256"]
            source_file = bundle_dir / name
            if not source_file.exists():
                raise RuntimeError(f"«بازیابی نامعتبر است؛ فایل پیدا نشد: {name}»")
            if sha256_file(source_file) != sha:
                raise RuntimeError("«بازیابی نامعتبر است؛ تطبیق هش انجام نشد.»")
            target = Path(destination) / name
            _copy_with_hash(source_file, target)

    def plan_retention(
        self,
        *,
        root: Path,
        max_age_days: int,
        max_total_bytes: int,
    ) -> RetentionPlan:
        now = self._clock().replace(tzinfo=timezone.utc)
        total_bytes = 0
        kept_bytes = 0
        freed_bytes = 0
        decisions: list[RetentionDecision] = []
        snapshots = sorted((path for path in Path(root).iterdir() if path.is_dir()), key=lambda p: p.name)
        for snapshot in snapshots:
            size = _dir_size(snapshot)
            age_seconds = max(0.0, (now - _snapshot_ts(snapshot.name, now)).total_seconds())
            age_days = int(age_seconds // 86400)
            total_bytes += size
            keep = age_days <= max_age_days
            reason = "age" if not keep else "within-policy"
            if keep and kept_bytes + size <= max_total_bytes:
                kept_bytes += size
                decisions.append(
                    RetentionDecision(path=snapshot, action="keep", reason=reason, size=size, age_days=age_days)
                )
            else:
                freed_bytes += size
                action = "remove"
                if keep and kept_bytes + size > max_total_bytes:
                    reason = "capacity"
                decisions.append(
                    RetentionDecision(path=snapshot, action=action, reason=reason, size=size, age_days=age_days)
                )
        return RetentionPlan(decisions=decisions, freed_bytes=freed_bytes, kept_bytes=kept_bytes)

    def apply_retention(self, *, plan: RetentionPlan, enforce: bool) -> None:
        for decision in plan.decisions:
            if decision.action == "remove" and enforce:
                shutil.rmtree(decision.path, ignore_errors=True)


def _copy_with_hash(source: Path, target: Path) -> tuple[str, int]:
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=target.name, suffix=".part", dir=target.parent)
    size = 0
    import hashlib

    hasher = hashlib.sha256()
    try:
        with os.fdopen(tmp_fd, "wb") as dst, source.open("rb") as src:
            for chunk in iter(lambda: sma.read(_BUFFER), b""):
                dst.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return hasher.hexdigest(), size


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for file in files:
            total += (Path(root) / file).stat().st_size
    return total


def _snapshot_ts(name: str, fallback: datetime) -> datetime:
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


__all__ = [
    "BackupManager",
    "BackupBundle",
    "BackupEntry",
    "RetentionPlan",
    "RetentionDecision",
]
