from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, Optional

from .exporter import ExportValidationError, ImportToSabtExporter
from .logging_utils import ExportLogger
from .metrics import ExporterMetrics
from .models import (
    Clock,
    ExportFilters,
    ExportJob,
    ExportJobStatus,
    ExportOptions,
    ExportSnapshot,
    RedisLike,
)
from .sanitization import deterministic_jitter

TRANSIENT_ERRORS = (OSError, ConnectionError, TimeoutError)


class DeterministicRedis(RedisLike):
    def __init__(self) -> None:
        self._store: Dict[str, str] = {}
        self._hash: Dict[str, Dict[str, str]] = {}
        self._ttl: Dict[str, Optional[int]] = {}
        self._lock = threading.Lock()

    def setnx(self, key: str, value: str, ex: int | None = None) -> bool:
        with self._lock:
            if key in self._store:
                return False
            self._store[key] = value
            self._ttl[key] = ex
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
            self._hash.pop(key, None)
            self._ttl.pop(key, None)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._store.get(key)

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        with self._lock:
            self._hash.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    def hgetall(self, key: str) -> dict[str, str]:
        with self._lock:
            return dict(self._hash.get(key, {}))

    def expire(self, key: str, ttl: int) -> None:  # pragma: no cover - deterministic noop
        with self._lock:
            if key in self._store:
                self._ttl[key] = ttl

    # helpers for tests
    def get_ttl(self, key: str) -> Optional[int]:
        with self._lock:
            return self._ttl.get(key)

    def flushdb(self) -> None:
        with self._lock:
            self._store.clear()
            self._hash.clear()
            self._ttl.clear()


class ExportJobRunner:
    def __init__(
        self,
        *,
        exporter: ImportToSabtExporter,
        redis: RedisLike | None = None,
        metrics: ExporterMetrics | None = None,
        logger: ExportLogger | None = None,
        clock: Clock,
        max_retries: int = 3,
    ) -> None:
        self.exporter = exporter
        self.redis = redis or DeterministicRedis()
        self.metrics = metrics or ExporterMetrics()
        self.logger = logger or ExportLogger()
        self.clock = clock
        self.max_retries = max_retries
        self.jobs: Dict[str, ExportJob] = {}
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}

    def submit(
        self,
        *,
        filters: ExportFilters,
        options: ExportOptions,
        idempotency_key: str,
        namespace: str,
    ) -> ExportJob:
        redis_key = f"phase6:exports:{namespace}:{idempotency_key}"
        if not self.redis.setnx(redis_key, "RUNNING", ex=86_400):
            data = self.redis.hgetall(redis_key)
            existing_id = data.get("job_id")
            if existing_id and existing_id in self.jobs:
                return self.jobs[existing_id]
            raise ValueError("EXPORT_DUPLICATE")
        job_id = str(uuid.uuid4())
        snapshot = ExportSnapshot(marker=f"snapshot-{job_id}", created_at=self.clock())
        job = ExportJob(
            id=job_id,
            status=ExportJobStatus.PENDING,
            filters=filters,
            options=options,
            snapshot=snapshot,
            namespace=namespace,
        )
        with self._lock:
            self.jobs[job_id] = job
        self.redis.hset(redis_key, {"job_id": job_id, "status": ExportJobStatus.PENDING.value})
        self.redis.expire(redis_key, 86_400)
        thread = threading.Thread(target=self._run_job, args=(job_id, redis_key), daemon=True)
        self._threads[job_id] = thread
        thread.start()
        return job

    def await_completion(self, job_id: str, timeout: float = 30.0) -> ExportJob:
        thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout=timeout)
        return self.jobs[job_id]

    def get_job(self, job_id: str) -> Optional[ExportJob]:
        return self.jobs.get(job_id)

    # internal
    def _run_job(self, job_id: str, redis_key: str) -> None:
        start_time = self.clock()
        self._update_job(job_id, status=ExportJobStatus.RUNNING, started_at=start_time)
        self.redis.hset(redis_key, {"status": ExportJobStatus.RUNNING.value})
        attempt = 0
        while True:
            attempt += 1
            try:
                manifest = self.exporter.run(
                    filters=self.jobs[job_id].filters,
                    options=self.jobs[job_id].options,
                    snapshot=self.jobs[job_id].snapshot,
                    clock_now=self.clock(),
                )
                duration = (self.clock() - start_time).total_seconds()
                self.metrics.observe_duration("export", duration)
                for file in manifest.files:
                    self.metrics.observe_file_bytes(file.byte_size)
                    self.metrics.observe_rows(file.row_count)
                self.metrics.inc_job(ExportJobStatus.SUCCESS.value)
                self._update_job(
                    job_id,
                    status=ExportJobStatus.SUCCESS,
                    finished_at=self.clock(),
                    manifest=manifest,
                )
                self.redis.hset(redis_key, {"status": ExportJobStatus.SUCCESS.value})
                self.redis.expire(redis_key, 86_400)
                self.logger.info(
                    "export_completed",
                    job_id=job_id,
                    rid=job_id,
                    namespace=self.jobs[job_id].namespace,
                    snapshot=self.jobs[job_id].snapshot.marker,
                    operation="export",
                    rows=manifest.total_rows,
                    last_error="",
                )
                break
            except ExportValidationError as exc:
                self.metrics.inc_error("validation")
                self.metrics.inc_job(ExportJobStatus.FAILED.value)
                self._update_job(
                    job_id,
                    status=ExportJobStatus.FAILED,
                    finished_at=self.clock(),
                    error=str(exc),
                )
                self.redis.hset(redis_key, {"status": ExportJobStatus.FAILED.value, "error": str(exc)})
                self.redis.expire(redis_key, 86_400)
                self.logger.error(
                    "export_failed",
                    job_id=job_id,
                    rid=job_id,
                    namespace=self.jobs[job_id].namespace,
                    snapshot=self.jobs[job_id].snapshot.marker,
                    operation="export",
                    last_error=str(exc),
                )
                break
            except TRANSIENT_ERRORS as exc:
                self.metrics.inc_error("transient")
                if attempt >= self.max_retries:
                    self.metrics.inc_job(ExportJobStatus.FAILED.value)
                    self._update_job(
                        job_id,
                        status=ExportJobStatus.FAILED,
                        finished_at=self.clock(),
                        error=str(exc),
                    )
                    self.redis.hset(
                        redis_key,
                        {"status": ExportJobStatus.FAILED.value, "error": str(exc)},
                    )
                    self.redis.expire(redis_key, 86_400)
                    self.logger.error(
                        "export_failed",
                        job_id=job_id,
                        rid=job_id,
                        namespace=self.jobs[job_id].namespace,
                        snapshot=self.jobs[job_id].snapshot.marker,
                        operation="export",
                        last_error=str(exc),
                    )
                    break
                delay = deterministic_jitter(0.1, attempt, job_id)
                time.sleep(delay)
                continue
            except Exception as exc:  # pragma: no cover - defensive logging
                self.metrics.inc_error("unknown")
                self.metrics.inc_job(ExportJobStatus.FAILED.value)
                self._update_job(
                    job_id,
                    status=ExportJobStatus.FAILED,
                    finished_at=self.clock(),
                    error=str(exc),
                )
                self.redis.hset(
                    redis_key,
                    {"status": ExportJobStatus.FAILED.value, "error": str(exc)},
                )
                self.redis.expire(redis_key, 86_400)
                self.logger.error(
                    "export_failed",
                    job_id=job_id,
                    rid=job_id,
                    namespace=self.jobs[job_id].namespace,
                    snapshot=self.jobs[job_id].snapshot.marker,
                    operation="export",
                    last_error=str(exc),
                )
                break

    def _update_job(self, job_id: str, **updates) -> None:
        with self._lock:
            job = self.jobs[job_id]
            updated = replace(job, **updates)
            self.jobs[job_id] = updated


__all__ = ["ExportJobRunner", "DeterministicRedis"]
