from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable

from pydantic import BaseModel, Field, field_validator

from src.reliability.clock import Clock


@dataclass(frozen=True)
class RetentionEntry:
    path: Path
    size_bytes: int
    modified_at: float
    created_at: float


class RetentionPolicy(BaseModel):
    """Retention window and thresholds for backup artifacts."""

    max_age_days: int = Field(ge=0, le=365)
    max_total_size_mb: int = Field(ge=1, le=4096)
    keep_latest: int = Field(default=1, ge=1, le=100)
    enforce: bool = True

    model_config = dict(extra="forbid")

    @field_validator("max_total_size_mb")
    @classmethod
    def _validate_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("حداکثر اندازه باید بزرگ‌تر از صفر باشد.")
        return value


class RetentionValidator:
    """Validate backup retention policy against filesystem timestamps and sizes."""

    def __init__(
        self,
        *,
        root: Path,
        clock: Clock,
        policy: RetentionPolicy,
    ) -> None:
        self._root = root
        self._clock = clock
        self._policy = policy

    def run(self) -> dict[str, object]:
        entries, removals = self._plan()
        dry_payload = self._render(entries, removals, mode="dry-run", removed_paths=set())
        removed_paths = set()
        if self._policy.enforce:
            removed_paths = self._enforce(removals)
        enforce_payload = self._render(entries, removals, mode="enforce", removed_paths=removed_paths)
        return {
            "policy": self._policy.model_dump(),
            "dry_run": dry_payload,
            "enforce": enforce_payload,
        }

    def _plan(self) -> tuple[list[RetentionEntry], Dict[Path, set[str]]]:
        entries = list(self._scan_entries())
        now_ts = self._clock.now().timestamp()
        policy = self._policy
        keep_set = {entry.path for entry in sorted(entries, key=lambda item: item.modified_at, reverse=True)[
            : policy.keep_latest
        ]}
        removals: Dict[Path, set[str]] = {}
        age_limit = timedelta(days=policy.max_age_days).total_seconds()
        size_limit_bytes = policy.max_total_size_mb * 1024 * 1024
        total_bytes = sum(entry.size_bytes for entry in entries)
        bytes_allowed = max(0, size_limit_bytes)
        bytes_over = max(0, total_bytes - bytes_allowed)
        # Age-based decisions
        for entry in entries:
            if entry.path in keep_set:
                continue
            age_delta = now_ts - entry.modified_at
            if age_limit and age_delta > age_limit:
                removals.setdefault(entry.path, set()).add("age")
        # Size-based decisions removing oldest until within limit
        if bytes_over > 0:
            for entry in sorted(entries, key=lambda item: item.modified_at):
                if entry.path in keep_set:
                    continue
                removals.setdefault(entry.path, set()).add("size")
                bytes_over -= entry.size_bytes
                if bytes_over <= 0:
                    break
        return entries, removals

    def _render(
        self,
        entries: Iterable[RetentionEntry],
        removals: Dict[Path, set[str]],
        *,
        mode: str,
        removed_paths: set[Path],
    ) -> dict[str, object]:
        retained_payload = []
        expired_payload = []
        removed_payload = []
        total_bytes = 0
        for entry in entries:
            total_bytes += entry.size_bytes
            reasons = sorted(removals.get(entry.path, set()))
            payload = self._entry_payload(entry, reasons)
            if reasons:
                expired_payload.append(payload)
            else:
                retained_payload.append(payload)
            if entry.path in removed_paths:
                removed_payload.append(payload)
        return {
            "mode": mode,
            "checked_at": self._clock.isoformat(),
            "total_bytes": total_bytes,
            "retained": retained_payload,
            "expired": expired_payload,
            "removed": removed_payload,
        }

    def _enforce(self, removals: Dict[Path, set[str]]) -> set[Path]:
        removed: set[Path] = set()
        for path in removals:
            try:
                path.unlink(missing_ok=True)
                removed.add(path)
            except OSError:
                continue
        return removed

    def _scan_entries(self) -> Iterable[RetentionEntry]:
        if not self._root.exists():
            return []
        for path in sorted(self._root.iterdir()):
            if path.is_file():
                stat = path.stat()
                yield RetentionEntry(
                    path=path,
                    size_bytes=stat.st_size,
                    modified_at=stat.st_mtime,
                    created_at=stat.st_ctime,
                )

    def _entry_payload(self, entry: RetentionEntry, reasons: list[str]) -> dict[str, object]:
        return {
            "path": str(entry.path),
            "size_bytes": entry.size_bytes,
            "modified_at": self._to_iso(entry.modified_at),
            "created_at": self._to_iso(entry.created_at),
            "reasons": reasons,
        }

    def _to_iso(self, timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=self._clock.timezone).isoformat()


__all__ = ["RetentionValidator", "RetentionPolicy"]
