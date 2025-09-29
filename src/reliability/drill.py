from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from pathlib import Path
from typing import List, Sequence

from .atomic import atomic_write_json
from .clock import Clock
from .logging_utils import JSONLogger, persian_error
from .metrics import ReliabilityMetrics


@dataclass(slots=True)
class BackupEntry:
    path: Path
    sha256: str
    size_bytes: int
    modified_at: float


@dataclass(slots=True)
class BackupResult:
    run_id: str
    started_at: str
    completed_at: str
    entries: Sequence[BackupEntry]
    total_bytes: int


@dataclass(slots=True)
class RestoreResult:
    started_at: str
    completed_at: str
    duration_s: float
    rpo_s: float
    verified: bool
    restored_bytes: int


def _derive_run_id(namespace: str, idempotency_key: str, tick_ms: int) -> str:
    payload = f"{namespace}|{idempotency_key}|{tick_ms}".encode("utf-8", "ignore")
    return blake2b(payload, digest_size=16).hexdigest()


class DisasterRecoveryDrill:
    def __init__(
        self,
        *,
        backups_root: Path,
        metrics: ReliabilityMetrics,
        logger: JSONLogger,
        clock: Clock,
        report_path: Path,
    ) -> None:
        self.backups_root = Path(backups_root)
        self.metrics = metrics
        self.logger = logger
        self.clock = clock
        self.report_path = Path(report_path)

    def run(
        self,
        source: Path,
        destination: Path,
        *,
        correlation_id: str,
        namespace: str = "default",
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        source = Path(source)
        destination = Path(destination)
        idem = (idempotency_key or correlation_id or "drill").strip() or "drill"
        start_instant = self.clock.now()
        tick_ms = int(max(0, start_instant.timestamp() * 1000))
        run_id = _derive_run_id(namespace, idem, tick_ms)
        backup_dir = self.backups_root / run_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        self.metrics.inflight_backups.inc()
        try:
            backup_result = self._perform_backup(
                source,
                backup_dir,
                namespace=namespace,
                started_at=start_instant,
            )
        finally:
            self.metrics.inflight_backups.dec()
        restore_result = self._perform_restore(
            backup_result,
            destination,
            namespace=namespace,
        )
        report = {
            "correlation_id": correlation_id,
            "run_id": run_id,
            "started_at": backup_result.started_at,
            "ended_at": restore_result.completed_at,
            "duration_s": max(
                0.0,
                self._seconds_between(backup_result.started_at, restore_result.completed_at),
            ),
            "rto_s": restore_result.duration_s,
            "rpo_s": restore_result.rpo_s,
            "rto_ms": int(round(restore_result.duration_s * 1000)),
            "rpo_ms": int(round(restore_result.rpo_s * 1000)),
            "sha256": [
                {
                    "path": str(entry.path),
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                }
                for entry in backup_result.entries
            ],
            "restored_bytes": restore_result.restored_bytes,
            "backed_up_bytes": backup_result.total_bytes,
        }
        atomic_write_json(self.report_path, report)
        self.metrics.mark_dr(status="success", namespace=namespace)
        self.metrics.mark_operation(
            operation="drill",
            outcome="success",
            reason="completed",
            namespace=namespace,
        )
        self.logger.bind(correlation_id).info(
            "dr.completed",
            report=report,
        )
        return report

    def _perform_backup(
        self,
        source: Path,
        destination: Path,
        *,
        namespace: str,
        started_at: datetime | None = None,
    ) -> BackupResult:
        start_dt = started_at or self.clock.now()
        entries: List[BackupEntry] = []
        total_bytes = 0
        for file_path in sorted(source.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(source)
            target = destination / rel
            sha = hashlib.sha256()
            size = 0
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            with file_path.open("rb") as src, tmp.open("wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    sha.update(chunk)
                    dst.write(chunk)
                    size += len(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(tmp, target)
            entry = BackupEntry(
                path=rel,
                sha256=sha.hexdigest(),
                size_bytes=size,
                modified_at=file_path.stat().st_mtime,
            )
            entries.append(entry)
            total_bytes += size
            self.metrics.add_dr_bytes(direction="backup", amount=size, namespace=namespace)
        end_dt = self.clock.now()
        result = BackupResult(
            run_id=destination.name,
            started_at=start_dt.isoformat(),
            completed_at=end_dt.isoformat(),
            entries=tuple(entries),
            total_bytes=total_bytes,
        )
        self.metrics.observe_duration("dr.backup", (end_dt - start_dt).total_seconds())
        return result

    def _perform_restore(
        self,
        backup: BackupResult,
        destination: Path,
        *,
        namespace: str,
    ) -> RestoreResult:
        start_dt = self.clock.now()
        restored_bytes = 0
        verified = True
        destination.mkdir(parents=True, exist_ok=True)
        for entry in backup.entries:
            source_file = self.backups_root / backup.run_id / entry.path
            target_file = destination / entry.path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            sha = hashlib.sha256()
            tmp = target_file.with_suffix(target_file.suffix + ".part")
            with source_file.open("rb") as src, tmp.open("wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    sha.update(chunk)
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(tmp, target_file)
            digest = sha.hexdigest()
            restored_bytes += entry.size_bytes
            if digest != entry.sha256:
                verified = False
            self.metrics.add_dr_bytes(
                direction="restore", amount=entry.size_bytes, namespace=namespace
            )
        end_dt = self.clock.now()
        duration = max(0.0, (end_dt - start_dt).total_seconds())
        completed_at = end_dt.isoformat()
        rpo = max(0.0, self._seconds_between(backup.completed_at, start_dt.isoformat()))
        self.metrics.observe_duration("dr.restore", duration)
        if not verified:
            self.metrics.mark_dr(status="checksum_mismatch", namespace=namespace)
            self.metrics.mark_operation(
                operation="drill",
                outcome="failure",
                reason="checksum_mismatch",
                namespace=namespace,
            )
            raise RuntimeError(
                persian_error(
                    "بازیابی پشتیبان موفق نبود؛ جمع کنترل تطابق ندارد.",
                    "DR_SHA_MISMATCH",
                    correlation_id=backup.run_id,
                )
            )
        return RestoreResult(
            started_at=start_dt.isoformat(),
            completed_at=completed_at,
            duration_s=duration,
            rpo_s=rpo,
            verified=verified,
            restored_bytes=restored_bytes,
        )

    def _seconds_between(self, start_iso: str, end_iso: str) -> float:
        from datetime import datetime

        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return (end - start).total_seconds()


__all__ = ["DisasterRecoveryDrill"]
