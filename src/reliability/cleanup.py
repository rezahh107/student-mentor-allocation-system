from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .atomic import atomic_write_json
from .clock import Clock
from .config import CleanupConfig
from .logging_utils import JSONLogger
from .metrics import ReliabilityMetrics


@dataclass(slots=True)
class CleanupResult:
    removed_part_files: List[str]
    removed_links: List[str]


class CleanupDaemon:
    def __init__(
        self,
        *,
        artifacts_root: Path,
        backups_root: Path,
        config: CleanupConfig,
        metrics: ReliabilityMetrics,
        clock: Clock,
        logger: JSONLogger,
        registry_path: Path | None = None,
        namespace: str = "default",
        report_path: Path | None = None,
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.backups_root = Path(backups_root)
        self.config = config
        self.metrics = metrics
        self.clock = clock
        self.logger = logger
        self.registry_path = Path(registry_path) if registry_path else self.artifacts_root / "signed_urls.json"
        self.namespace = namespace or "default"
        self.report_path = Path(report_path) if report_path else None

    def run(self) -> CleanupResult:
        removed_parts = self._cleanup_part_files()
        removed_links = self._cleanup_links()
        reason = "completed"
        if not removed_parts and not removed_links:
            reason = "no_action"
        self.metrics.mark_operation(
            operation="cleanup",
            outcome="success",
            reason=reason,
            namespace=self.namespace,
        )
        result = CleanupResult(removed_part_files=removed_parts, removed_links=removed_links)
        self._write_report(result, reason=reason)
        return result

    def _cleanup_part_files(self) -> List[str]:
        removed: List[str] = []
        cutoff = self.clock.now().timestamp() - self.config.part_max_age
        for root in (self.artifacts_root, self.backups_root):
            if not root.exists():
                continue
            for path in root.rglob("*.part"):
                try:
                    if path.stat().st_mtime <= cutoff:
                        path.unlink(missing_ok=True)
                        removed.append(str(path))
                        self.metrics.mark_cleanup(kind="part_file", namespace=self.namespace)
                        self.logger.bind("cleanup-part").info(
                            "cleanup.removed_part",
                            path=str(path),
                        )
                except OSError:
                    continue
        return removed

    def _cleanup_links(self) -> List[str]:
        registry = self._load_registry()
        now = self.clock.now().timestamp()
        kept: Dict[str, dict] = {}
        removed: List[str] = []
        for key, payload in registry.items():
            expires_at = float(payload.get("expires_at") or 0)
            created_at = float(payload.get("created_at") or 0)
            ttl_expired = created_at and (created_at + self.config.link_ttl <= now)
            expires_expired = expires_at and expires_at <= now
            if ttl_expired or expires_expired:
                removed.append(key)
                self.metrics.mark_cleanup(kind="signed_url", namespace=self.namespace)
                self.logger.bind("cleanup-link").info(
                    "cleanup.removed_link",
                    token=key,
                )
            else:
                kept[key] = payload
        if self.registry_path:
            atomic_write_json(self.registry_path, kept)
        return removed

    def _load_registry(self) -> Dict[str, dict]:
        if not self.registry_path or not self.registry_path.exists():
            return {}
        try:
            with self.registry_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except json.JSONDecodeError:
            return {}
        return {}

    def _write_report(self, result: CleanupResult, *, reason: str) -> None:
        if not self.report_path:
            return
        payload = {
            "timestamp": self.clock.now().isoformat(),
            "namespace": self.namespace,
            "reason": reason,
            "removed_part_files": result.removed_part_files,
            "removed_links": result.removed_links,
        }
        atomic_write_json(self.report_path, payload)


__all__ = ["CleanupDaemon", "CleanupResult"]
