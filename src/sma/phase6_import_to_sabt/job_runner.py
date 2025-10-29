from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, Optional

from sma.core.retry import RetryExhaustedError

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock
from sma.phase6_import_to_sabt.errors import (
    EXPORT_IO_FA_MESSAGE,
    EXPORT_VALIDATION_FA_MESSAGE,
    make_error,
)
from sma.phase6_import_to_sabt.export_runner import RetryingExportRunner
from sma.phase6_import_to_sabt.exporter import ExportIOError, ExportValidationError, ImportToSabtExporter
from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.models import (
    ExportExecutionStats,
    ExportFilters,
    ExportJob,
    ExportJobStatus,
    ExportOptions,
    ExportManifest,
    ExportSnapshot,
    RedisLike,
)
from sma.phase6_import_to_sabt.sanitization import dumps_json

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
            value = self._ttl.get(key)
            if value is not None:
                return value
            parts = key.split(":")
            if len(parts) < 2:
                return None
            prefix_parts = parts[:-1]
            suffix = parts[-1]
            for candidate, ttl in self._ttl.items():
                candidate_parts = candidate.split(":")
                if (
                    len(candidate_parts) == len(prefix_parts) + 2
                    and candidate_parts[-1] == suffix
                    and candidate_parts[-2] in {"csv", "xlsx"}
                    and candidate_parts[:-2] == prefix_parts
                ):
                    return ttl
            return None

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
        clock: Clock | Callable[[], datetime] | None = None,
        max_retries: int = 3,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.exporter = exporter
        self.redis = redis or DeterministicRedis()
        self.metrics = metrics or ExporterMetrics()
        self.logger = logger or ExportLogger()
        self.clock = ensure_clock(clock, timezone="Asia/Tehran")
        self.max_retries = max_retries
        self.jobs: Dict[str, ExportJob] = {}
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}
        self._sleep = sleeper or time.sleep
        base_sleep = self._sleep

        def _runner_sleep(delay: float) -> None:
            self.metrics.observe_retry(phase="job", outcome="retry")
            base_sleep(delay)

        self.retry_runner = RetryingExportRunner(
            retryable=TRANSIENT_ERRORS,
            clock=self.clock,
            sleeper=_runner_sleep,
            metrics=self.metrics,
            base_delay=0.1,
            max_attempts=self.max_retries,
        )
        attach = getattr(self.exporter, "attach_metrics", None)
        if callable(attach):
            attach(self.metrics)

    def submit(
        self,
        *,
        filters: ExportFilters,
        options: ExportOptions,
        idempotency_key: str,
        namespace: str,
        correlation_id: str,
        ) -> ExportJob:
        redis_key = f"phase6:exports:{namespace}:{idempotency_key}"
        if not self.redis.setnx(redis_key, "RUNNING", ex=86_400):
            data = self.redis.hgetall(redis_key)
            existing_id = data.get("job_id")
            if existing_id and existing_id in self.jobs:
                return self.jobs[existing_id]
            raise ValueError("EXPORT_DUPLICATE")
        job_id = str(uuid.uuid4())
        now = self.clock.now()
        snapshot = ExportSnapshot(marker=f"snapshot-{job_id}", created_at=now)
        job = ExportJob(
            id=job_id,
            status=ExportJobStatus.PENDING,
            filters=filters,
            options=options,
            snapshot=snapshot,
            namespace=namespace,
            correlation_id=correlation_id,
            queued_at=now,
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
        start_time = self.clock.now()
        job = self.jobs[job_id]
        format_label = job.options.output_format
        queue_duration = (start_time - job.queued_at).total_seconds()
        if queue_duration >= 0:
            self.metrics.observe_duration("queue", queue_duration, format_label)
        self._update_job(job_id, status=ExportJobStatus.RUNNING, started_at=start_time)
        self.redis.hset(redis_key, {"status": ExportJobStatus.RUNNING.value})
        job = self.jobs[job_id]

        def _execute_once() -> tuple[ExportManifest, ExportExecutionStats]:
            stats = ExportExecutionStats()
            manifest = self.exporter.run(
                filters=job.filters,
                options=job.options,
                snapshot=job.snapshot,
                clock_now=start_time,
                stats=stats,
                correlation_id=job.correlation_id,
            )
            return manifest, stats

        try:
            manifest, stats = self.retry_runner.execute(
                _execute_once,
                reason="job",
                correlation_id=job.correlation_id,
            )
        except ExportValidationError as exc:
            error_payload = make_error("EXPORT_VALIDATION_ERROR", EXPORT_VALIDATION_FA_MESSAGE).as_dict()
            error_payload["detail"] = str(exc)
            self.metrics.inc_error("validation", format_label)
            self.metrics.inc_job(ExportJobStatus.FAILED.value, format_label)
            self._update_job(
                job_id,
                status=ExportJobStatus.FAILED,
                finished_at=self.clock.now(),
                error=error_payload,
            )
            self.redis.hset(
                redis_key,
                {
                    "status": ExportJobStatus.FAILED.value,
                    "error": dumps_json(error_payload),
                },
            )
            self.redis.expire(redis_key, 86_400)
            self.logger.error(
                "export_failed",
                job_id=job_id,
                rid=job_id,
                namespace=job.namespace,
                snapshot=job.snapshot.marker,
                operation="export",
                last_error=error_payload["error_code"],
                correlation_id=self.jobs[job_id].correlation_id,
            )
            return
        except (ExportIOError, RetryExhaustedError) as exc:
            error_payload = make_error("EXPORT_IO_ERROR", EXPORT_IO_FA_MESSAGE).as_dict()
            error_payload["detail"] = type(exc).__name__
            self.metrics.inc_error("io", format_label)
            if isinstance(exc, RetryExhaustedError):
                self.metrics.observe_retry_exhaustion(phase="job")
            self.metrics.inc_job(ExportJobStatus.FAILED.value, format_label)
            self._update_job(
                job_id,
                status=ExportJobStatus.FAILED,
                finished_at=self.clock.now(),
                error=error_payload,
            )
            self.redis.hset(
                redis_key,
                {
                    "status": ExportJobStatus.FAILED.value,
                    "error": dumps_json(error_payload),
                },
            )
            self.redis.expire(redis_key, 86_400)
            self.logger.error(
                "export_failed",
                job_id=job_id,
                rid=job_id,
                namespace=self.jobs[job_id].namespace,
                snapshot=self.jobs[job_id].snapshot.marker,
                operation="export",
                last_error=error_payload["error_code"],
                correlation_id=self.jobs[job_id].correlation_id,
            )
            return
        except TRANSIENT_ERRORS as exc:
            self.metrics.inc_error("transient", format_label)
            self.metrics.observe_retry_exhaustion(phase="job")
            error_payload = make_error("EXPORT_IO_ERROR", EXPORT_IO_FA_MESSAGE).as_dict()
            error_payload["detail"] = str(exc)
            self.metrics.inc_job(ExportJobStatus.FAILED.value, format_label)
            self._update_job(
                job_id,
                status=ExportJobStatus.FAILED,
                finished_at=self.clock.now(),
                error=error_payload,
            )
            self.redis.hset(
                redis_key,
                {
                    "status": ExportJobStatus.FAILED.value,
                    "error": dumps_json(error_payload),
                },
            )
            self.redis.expire(redis_key, 86_400)
            self.logger.error(
                "export_failed",
                job_id=job_id,
                rid=job_id,
                namespace=self.jobs[job_id].namespace,
                snapshot=self.jobs[job_id].snapshot.marker,
                operation="export",
                last_error=error_payload["error_code"],
                correlation_id=self.jobs[job_id].correlation_id,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            self.metrics.inc_error("unknown", format_label)
            self.metrics.inc_job(ExportJobStatus.FAILED.value, format_label)
            error_payload = make_error("EXPORT_IO_ERROR", EXPORT_IO_FA_MESSAGE).as_dict()
            error_payload["detail"] = type(exc).__name__
            self._update_job(
                job_id,
                status=ExportJobStatus.FAILED,
                finished_at=self.clock.now(),
                error=error_payload,
            )
            self.redis.hset(
                redis_key,
                {
                    "status": ExportJobStatus.FAILED.value,
                    "error": dumps_json(error_payload),
                },
            )
            self.redis.expire(redis_key, 86_400)
            self.logger.error(
                "export_failed",
                job_id=job_id,
                rid=job_id,
                namespace=job.namespace,
                snapshot=job.snapshot.marker,
                operation="export",
                last_error=error_payload["error_code"],
                correlation_id=self.jobs[job_id].correlation_id,
            )
            return

        duration = (self.clock.now() - start_time).total_seconds()
        self.metrics.observe_duration("total", duration, format_label)
        for phase, value in stats.phase_durations.items():
            self.metrics.observe_duration(phase, value, format_label)
        for file in manifest.files:
            self.metrics.observe_file_bytes(file.byte_size, format_label)
            self.metrics.observe_rows(file.row_count, format_label)
        self.metrics.inc_job(ExportJobStatus.SUCCESS.value, format_label)
        self._update_job(
            job_id,
            status=ExportJobStatus.SUCCESS,
            finished_at=self.clock.now(),
            manifest=manifest,
        )
        self.redis.hset(redis_key, {"status": ExportJobStatus.SUCCESS.value})
        self.redis.expire(redis_key, 86_400)
        self.logger.info(
            "export_completed",
            job_id=job_id,
            rid=job_id,
            namespace=job.namespace,
            snapshot=job.snapshot.marker,
            operation="export",
            rows=manifest.total_rows,
            last_error="",
            correlation_id=self.jobs[job_id].correlation_id,
        )

    def _update_job(self, job_id: str, **updates) -> None:
        with self._lock:
            job = self.jobs[job_id]
            updated = replace(job, **updates)
            self.jobs[job_id] = updated


__all__ = ["ExportJobRunner", "DeterministicRedis"]
