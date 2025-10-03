from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from phase6_import_to_sabt.xlsx.metrics import ImportExportMetrics
from phase6_import_to_sabt.xlsx.retry import retry_with_backoff
from phase6_import_to_sabt.xlsx.utils import dumps_deterministic


class SupportsRedisHash(Protocol):
    def hset(self, key: str, mapping: dict[str, str]) -> None:  # pragma: no cover - protocol
        ...

    def hgetall(self, key: str) -> dict[str, str]:  # pragma: no cover - protocol
        ...

    def expire(self, key: str, ttl: int) -> None:  # pragma: no cover - protocol
        ...

    def delete(self, key: str) -> None:  # pragma: no cover - protocol
        ...


def _ensure_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _deepcopy(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(dumps_deterministic(payload))


@dataclass(slots=True)
class ExportJobStore(Protocol):
    def begin(
        self,
        job_id: str,
        *,
        file_format: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:  # pragma: no cover - interface
        ...

    def complete(
        self,
        job_id: str,
        *,
        artifact_path: str,
        manifest_path: str,
        files: list[dict[str, Any]],
        excel_safety: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:  # pragma: no cover - interface
        ...

    def fail(self, job_id: str, *, error: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - interface
        ...

    def load(self, job_id: str) -> dict[str, Any] | None:  # pragma: no cover - interface
        ...


@dataclass(slots=True)
class InMemoryExportJobStore:
    now: Callable[[], str]
    metrics: ImportExportMetrics | None = None
    _jobs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def begin(self, job_id: str, *, file_format: str, filters: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": job_id,
            "status": "PENDING",
            "format": file_format,
            "filters": filters,
            "created_at": self.now(),
            "updated_at": self.now(),
            "files": [],
            "artifact_path": "",
            "manifest_path": "",
            "excel_safety": {},
            "manifest": {},
            "error": None,
        }
        self._jobs[job_id] = _deepcopy(payload)
        return _deepcopy(payload)

    def complete(
        self,
        job_id: str,
        *,
        artifact_path: str,
        manifest_path: str,
        files: list[dict[str, Any]],
        excel_safety: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._jobs.get(job_id) or self.begin(job_id, file_format="unknown", filters={})
        payload.update(
            {
                "status": "SUCCESS",
                "updated_at": self.now(),
                "artifact_path": artifact_path,
                "manifest_path": manifest_path,
                "files": files,
                "excel_safety": excel_safety,
                "manifest": manifest,
                "error": None,
            }
        )
        self._jobs[job_id] = _deepcopy(payload)
        return _deepcopy(payload)

    def fail(self, job_id: str, *, error: dict[str, Any]) -> dict[str, Any]:
        payload = self._jobs.get(job_id) or self.begin(job_id, file_format="unknown", filters={})
        payload.update({"status": "FAILED", "updated_at": self.now(), "error": error})
        self._jobs[job_id] = _deepcopy(payload)
        return _deepcopy(payload)

    def load(self, job_id: str) -> dict[str, Any] | None:
        payload = self._jobs.get(job_id)
        return _deepcopy(payload) if payload else None


@dataclass(slots=True)
class RedisExportJobStore:
    redis: SupportsRedisHash
    namespace: str
    now: Callable[[], str]
    metrics: ImportExportMetrics | None = None
    ttl_seconds: int = 86_400
    attempts: int = 5
    base_delay: float = 0.01
    sleeper: Callable[[float], None] | None = None

    def _key(self, job_id: str) -> str:
        return f"{self.namespace}:export:{job_id}"

    def begin(self, job_id: str, *, file_format: str, filters: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": job_id,
            "status": "PENDING",
            "format": file_format,
            "filters": filters,
            "created_at": self.now(),
            "updated_at": self.now(),
            "files": [],
            "artifact_path": "",
            "manifest_path": "",
            "excel_safety": {},
            "manifest": {},
            "error": None,
        }
        self._write(job_id, payload, operation="begin")
        return payload

    def complete(
        self,
        job_id: str,
        *,
        artifact_path: str,
        manifest_path: str,
        files: list[dict[str, Any]],
        excel_safety: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self.load(job_id) or self.begin(job_id, file_format="unknown", filters={})
        payload.update(
            {
                "status": "SUCCESS",
                "updated_at": self.now(),
                "artifact_path": artifact_path,
                "manifest_path": manifest_path,
                "files": files,
                "excel_safety": excel_safety,
                "manifest": manifest,
                "error": None,
            }
        )
        self._write(job_id, payload, operation="complete")
        return payload

    def fail(self, job_id: str, *, error: dict[str, Any]) -> dict[str, Any]:
        payload = self.load(job_id) or self.begin(job_id, file_format="unknown", filters={})
        payload.update({"status": "FAILED", "updated_at": self.now(), "error": error})
        self._write(job_id, payload, operation="fail")
        return payload

    def load(self, job_id: str) -> dict[str, Any] | None:
        key = self._key(job_id)

        def _read(_: int) -> dict[str, Any]:
            return self.redis.hgetall(key)

        raw = retry_with_backoff(
            _read,
            attempts=self.attempts,
            base_delay=self.base_delay,
            seed="redis_read",
            metrics=self.metrics,
            format_label="n/a",
            sleeper=self.sleeper,
        )
        payload_raw = raw.get("payload") if raw else None
        if not payload_raw:
            return None
        return json.loads(_ensure_text(payload_raw))

    def _write(self, job_id: str, payload: dict[str, Any], *, operation: str) -> None:
        key = self._key(job_id)
        serialized = dumps_deterministic(payload)

        def _op(_: int) -> None:
            self.redis.hset(key, {"payload": serialized})
            self.redis.expire(key, self.ttl_seconds)

        retry_with_backoff(
            _op,
            attempts=self.attempts,
            base_delay=self.base_delay,
            seed=f"redis_{operation}",
            metrics=self.metrics,
            format_label="n/a",
            sleeper=self.sleeper,
        )


__all__ = [
    "ExportJobStore",
    "InMemoryExportJobStore",
    "RedisExportJobStore",
]
