from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterator, Tuple

from redis import Redis
from sqlalchemy.exc import IntegrityError

from .clock import Clock
from .config import UploadsConfig
from .errors import UploadError, envelope
from .logging_utils import setup_json_logging
from .metrics import UploadsMetrics
from .repository import UploadRecord, UploadRepository
from .retry import retry
from .storage import AtomicStorage
from .validator import CSVValidator
from .zip_utils import ZipCSVStream, iter_csv_from_zip


CHUNK_SIZE = 4 * 1024 * 1024


@dataclass(slots=True)
class UploadContext:
    profile: str
    year: int
    filename: str
    rid: str
    namespace: str
    idempotency_key: str


class UploadService:
    def __init__(
        self,
        *,
        config: UploadsConfig,
        repository: UploadRepository,
        storage: AtomicStorage,
        validator: CSVValidator,
        redis_client: Redis,
        metrics: UploadsMetrics,
        clock: Clock,
    ) -> None:
        self.config = config
        self.repository = repository
        self.storage = storage
        self.validator = validator
        self.redis = redis_client
        self.metrics = metrics
        self.clock = clock
        self.logger = setup_json_logging()

    # --------------- helpers ---------------
    def _read_stream(self, file_obj) -> bytes:
        data = bytearray()
        while True:
            chunk = file_obj.read(CHUNK_SIZE)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > self.config.max_upload_bytes:
                raise UploadError(envelope("UPLOAD_SIZE_EXCEEDED"))
        return bytes(data)

    def _detect_format(self, filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".csv"):
            return "csv"
        if lower.endswith(".zip"):
            return "zip"
        raise UploadError(envelope("UPLOAD_FORMAT_UNSUPPORTED"))

    def _validate_crlf(self, chunk: bytes, previous: int | None) -> int | None:
        last = previous
        for index, byte in enumerate(chunk):
            if byte == 10:  # \n
                prev = chunk[index - 1] if index > 0 else last
                if prev != 13:
                    raise UploadError(
                        envelope(
                            "UPLOAD_VALIDATION_ERROR",
                            details={"reason": "CRLF_REQUIRED"},
                        )
                    )
            last = byte
        return last

    def _write_csv(self, chunks: Iterator[bytes]) -> Tuple[str, Path, int]:
        writer = self.storage.writer()
        digest = sha256()
        total = 0
        last_byte: int | None = None
        for chunk in chunks:
            total += len(chunk)
            if total > self.config.max_upload_bytes:
                writer.abort()
                raise UploadError(envelope("UPLOAD_SIZE_EXCEEDED"))
            last_byte = self._validate_crlf(chunk, last_byte)
            digest.update(chunk)
            writer.write(chunk)
        sha_hex = digest.hexdigest()
        path = self.storage.finalize(sha_hex, writer)
        return sha_hex, path, total

    def _create_manifest(
        self,
        record: UploadRecord,
        sha_hex: str,
        size_bytes: int,
        validation,
    ) -> Path:
        generated_at = self.clock.now().isoformat()
        manifest = {
            "sha256": sha_hex,
            "record_count": validation.record_count,
            "size_bytes": size_bytes,
            "generated_at": generated_at,
            "meta": {
                "profile": record.profile,
                "year": record.year,
                "source_filename": record.source_filename,
            },
            "preview": validation.preview_rows,
        }
        manifest_path = (
            self.config.manifest_dir
            / record.namespace
            / f"{record.id}_upload_manifest.json"
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = manifest_path.with_suffix(".part")
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, manifest_path)
        return manifest_path

    def _acquire_idempotency(self, context: UploadContext) -> tuple[str | None, str]:
        redis_key = f"uploads:{self.config.namespace}:{context.namespace}:idem:{context.idempotency_key}"
        placeholder = f"pending:{context.rid}"
        if not self.redis.set(redis_key, placeholder, nx=True, ex=self.config.idempotency_ttl_seconds):
            existing = self.redis.get(redis_key)
            if existing:
                decoded = existing.decode()
                if decoded.startswith("upload:"):
                    return decoded.split(":", 1)[1], redis_key
            raise UploadError(envelope("UPLOAD_CONFLICT"))
        return None, redis_key

    def _finalize_idempotency(self, redis_key: str, upload_id: str) -> None:
        self.redis.set(redis_key, f"upload:{upload_id}", ex=self.config.idempotency_ttl_seconds)

    def _activation_lock_key(self, year: int) -> str:
        return f"uploads:{self.config.namespace}:activate:{year}"

    # --------------- public API ---------------
    def upload(self, context: UploadContext, file_obj) -> UploadRecord:
        start = time.perf_counter()
        fmt = self._detect_format(context.filename)
        existing_id, redis_key = self._acquire_idempotency(context)
        if existing_id:
            return self.repository.get(existing_id)
        try:
            raw_bytes = self._read_stream(file_obj)
            if fmt == "zip":
                inner_name, csv_stream = iter_csv_from_zip(raw_bytes)
                filename = inner_name

                def chunk_factory() -> Iterator[bytes]:
                    return iter(csv_stream)

            else:
                filename = context.filename

                def chunk_factory() -> Iterator[bytes]:
                    return self._iter_chunks(raw_bytes)

            def do_write() -> Tuple[str, Path, int]:
                return self._write_csv(chunk_factory())

            sha_hex, path, size_bytes = retry(
                do_write,
                self.config.retry_attempts,
                base_delay=self.config.retry_base_delay,
                max_delay=self.config.retry_max_delay,
                fatal_exceptions=(UploadError,),
            )

            record = self.repository.create_upload(
                profile=context.profile,
                year=context.year,
                namespace=context.namespace,
                clock_now=self.clock.now(),
                source_filename=filename,
            )
            validation = self.validator.validate(path)
            manifest_path = self._create_manifest(record, sha_hex, size_bytes, validation)
            updated = self.repository.update_manifest(
                record.id,
                sha256=sha_hex,
                record_count=validation.record_count,
                size_bytes=size_bytes,
                manifest_path=str(manifest_path),
                clock_now=self.clock.now(),
            )
            self._finalize_idempotency(redis_key, updated.id)
            duration = time.perf_counter() - start
            self.metrics.record_success(fmt, duration, size_bytes)
            self.logger.info(
                "upload completed",
                extra={
                    "ctx_rid": context.rid,
                    "ctx_op": "upload",
                    "ctx_namespace": context.namespace,
                    "ctx_last_error": None,
                    "sha": sha_hex,
                    "records": validation.record_count,
                },
            )
            return updated
        except UploadError as exc:
            self.metrics.record_failure(fmt, exc.envelope.code)
            self.logger.error(
                exc.envelope.message,
                extra={
                    "ctx_rid": context.rid,
                    "ctx_op": "upload",
                    "ctx_namespace": context.namespace,
                    "ctx_last_error": exc.envelope.code,
                },
            )
            self.redis.delete(redis_key)
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self.metrics.record_failure(fmt, "INTERNAL_ERROR")
            self.logger.exception(
                "upload failed",
                extra={
                    "ctx_rid": context.rid,
                    "ctx_op": "upload",
                    "ctx_namespace": context.namespace,
                    "ctx_last_error": str(exc),
                },
            )
            self.redis.delete(redis_key)
            raise UploadError(envelope("UPLOAD_INTERNAL_ERROR")) from exc

    def _iter_chunks(self, data: bytes) -> Iterator[bytes]:
        for index in range(0, len(data), CHUNK_SIZE):
            yield data[index : index + CHUNK_SIZE]

    def get_upload(self, upload_id: str) -> UploadRecord:
        try:
            return self.repository.get(upload_id)
        except KeyError as exc:
            raise UploadError(envelope("UPLOAD_NOT_FOUND")) from exc

    def activate(self, upload_id: str, *, rid: str, namespace: str) -> UploadRecord:
        lock_key = self._activation_lock_key(self.get_upload(upload_id).year)
        if not self.redis.set(lock_key, rid, nx=True, ex=self.config.idempotency_ttl_seconds):
            raise UploadError(envelope("UPLOAD_ACTIVATION_CONFLICT"))
        try:
            updated = self.repository.activate(upload_id, clock_now=self.clock.now())
            self.logger.info(
                "upload activated",
                extra={
                    "ctx_rid": rid,
                    "ctx_op": "activate",
                    "ctx_namespace": namespace,
                    "ctx_last_error": None,
                },
            )
            return updated
        except ValueError as exc:
            reason = str(exc)
            if reason == "upload not ready":
                raise UploadError(envelope("UPLOAD_ACTIVATION_CONFLICT")) from exc
            raise UploadError(
                envelope("UPLOAD_VALIDATION_ERROR", details={"reason": reason})
            ) from exc
        except IntegrityError as exc:
            raise UploadError(envelope("UPLOAD_ACTIVATION_CONFLICT")) from exc
        except Exception as exc:
            raise UploadError(envelope("UPLOAD_INTERNAL_ERROR")) from exc
        finally:
            self.redis.delete(lock_key)
