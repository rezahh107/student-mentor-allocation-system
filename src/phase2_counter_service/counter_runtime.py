"""Redis-backed counter allocation runtime for Phase 2."""
from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from hashlib import blake2s
from typing import Any, Mapping

from src.core.normalize import normalize_digits
from src.hardened_api.redis_support import RedisExecutor, RedisLike, RedisNamespaces

from .academic_year import AcademicYearProvider
from .runtime_metrics import CounterRuntimeMetrics
from .validation import COUNTER_PREFIX, COUNTER_PATTERN

logger = logging.getLogger("counter.runtime")


def _strip_controls(value: str) -> str:
    return "".join(
        ch for ch in value if ord(ch) not in {0x200c, 0x200d, 0x200e, 0x200f, 0xfeff}
    )


def _normalize_identifier(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    text = _strip_controls(text)
    text = text.strip()
    if not text:
        raise ValueError("شناسه دانش‌آموز نامعتبر است")
    return text


def _normalize_int_field(value: Any, *, field: str, allowed: set[int]) -> int:
    text = "" if value is None else str(value)
    normalized = normalize_digits(unicodedata.normalize("NFKC", text))
    normalized = _strip_controls(normalized).strip()
    if not normalized.isdigit():
        raise ValueError(f"{field} نامعتبر است")
    parsed = int(normalized)
    if parsed not in allowed:
        raise ValueError(f"{field} نامعتبر است")
    return parsed


def _hash_student(student_id: str, *, salt: str) -> str:
    digest = blake2s(key=salt.encode("utf-8"), digest_size=16)
    digest.update(student_id.encode("utf-8"))
    return digest.hexdigest()


@dataclass(slots=True)
class CounterResult:
    counter: str
    year_code: str
    status: str


class CounterRuntimeError(Exception):
    def __init__(self, code: str, message_fa: str, *, details: str | None = None) -> None:
        super().__init__(message_fa)
        self.code = code
        self.message_fa = message_fa
        self.details = details


class CounterRuntime:
    """High-level orchestrator for counter allocation via Redis."""

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        executor: RedisExecutor,
        metrics: CounterRuntimeMetrics,
        year_provider: AcademicYearProvider,
        hash_salt: str,
        max_serial: int = 9999,
        placeholder_ttl_ms: int = 5000,
        wait_attempts: int = 5,
        wait_base_ms: int = 20,
        wait_max_ms: int = 200,
    ) -> None:
        self._redis = redis
        self._namespaces = namespaces
        self._executor = executor
        self._metrics = metrics
        self._year_provider = year_provider
        self._hash_salt = hash_salt
        self._max_serial = max_serial
        self._placeholder_ttl = max(100, placeholder_ttl_ms)
        self._wait_attempts = max(1, wait_attempts)
        self._wait_base = max(5, wait_base_ms)
        self._wait_max = max(self._wait_base, wait_max_ms)

    async def allocate(self, payload: Mapping[str, Any], *, correlation_id: str) -> CounterResult:
        try:
            normalized = self._normalize_payload(payload)
        except ValueError as exc:
            self._metrics.record_alloc("validation_error")
            raise CounterRuntimeError(
                "COUNTER_VALIDATION_ERROR",
                "درخواست نامعتبر است؛ سال/جنسیت/مرکز را بررسی کنید.",
                details=str(exc),
            ) from exc

        student_hash = _hash_student(normalized["student_id"], salt=self._hash_salt)
        logger.info(
            json.dumps(
                {
                    "event": "counter.allocate.start",
                    "correlation_id": correlation_id,
                    "student": student_hash,
                    "year": normalized["year"],
                    "year_code": normalized["year_code"],
                    "gender": normalized["gender"],
                    "center": normalized["center"],
                },
                ensure_ascii=False,
            )
        )

        result = await self._allocate_with_retry(normalized, correlation_id, student_hash)
        logger.info(
            json.dumps(
                {
                    "event": "counter.allocate.finish",
                    "correlation_id": correlation_id,
                    "student": student_hash,
                    "counter": result.counter,
                    "status": result.status,
                },
                ensure_ascii=False,
            )
        )
        return result

    async def preview(self, payload: Mapping[str, Any]) -> CounterResult:
        try:
            year = payload.get("year")
            gender = _normalize_int_field(payload.get("gender"), field="جنسیت", allowed={0, 1})
            center = _normalize_int_field(payload.get("center"), field="مرکز", allowed={0, 1, 2})
            year_code = self._year_provider.code_for(year)
        except ValueError as exc:
            raise CounterRuntimeError(
                "COUNTER_VALIDATION_ERROR",
                "درخواست نامعتبر است؛ سال/جنسیت/مرکز را بررسی کنید.",
                details=str(exc),
            ) from exc

        sequence_key = self._namespaces.counter_sequence(year_code, gender)

        async def _fetch_current() -> int:
            raw = await self._redis.get(sequence_key)
            if raw is None:
                return 0
            if isinstance(raw, bytes):
                try:
                    return int(raw.decode("utf-8"))
                except ValueError:
                    return 0
            try:
                return int(raw)
            except ValueError:
                return 0

        current = await self._executor.call(
            _fetch_current,
            op_name="counter_preview",
        )
        next_serial = current + 1
        if next_serial > self._max_serial:
            self._metrics.record_exhausted(year_code, gender)
            raise CounterRuntimeError(
                "COUNTER_EXHAUSTED",
                "ظرفیت شماره ثبت برای این سال تکمیل شده است.",
            )
        counter = f"{year_code}{COUNTER_PREFIX[gender]}{next_serial:04d}"
        return CounterResult(counter=counter, year_code=year_code, status="preview")

    def _normalize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        year = payload.get("year")
        gender = _normalize_int_field(payload.get("gender"), field="جنسیت", allowed={0, 1})
        center = _normalize_int_field(payload.get("center"), field="مرکز", allowed={0, 1, 2})
        student_id = _normalize_identifier(payload.get("student_id"))
        year_code = self._year_provider.code_for(year)
        normalized_year = normalize_digits(unicodedata.normalize("NFKC", str(year)))
        normalized_year = _strip_controls(normalized_year).strip()
        return {
            "year": normalized_year,
            "year_code": year_code,
            "gender": gender,
            "center": center,
            "student_id": student_id,
        }

    async def _allocate_with_retry(
        self,
        normalized: Mapping[str, Any],
        correlation_id: str,
        student_hash: str,
    ) -> CounterResult:
        student_key = self._namespaces.counter_student(normalized["year_code"], normalized["student_id"])
        sequence_key = self._namespaces.counter_sequence(normalized["year_code"], normalized["gender"])

        async def _run_script() -> str:
            return await self._redis.eval(
                _ALLOCATE_SCRIPT,
                2,
                student_key,
                sequence_key,
                _PENDING_JSON,
                normalized["year_code"],
                COUNTER_PREFIX[normalized["gender"]],
                str(normalized["center"]),
                str(normalized["gender"]),
                str(self._max_serial),
                str(self._placeholder_ttl),
            )

        backoff = self._wait_base / 1000.0
        attempts = 0
        for attempt in range(1, self._wait_attempts + 1):
            attempts = attempt
            response = await self._executor.call(
                _run_script,
                op_name="counter_allocate",
                correlation_id=correlation_id,
            )
            result = json.loads(response)
            status = result.get("status")
            if status == "NEW":
                counter = result["counter"]
                if not COUNTER_PATTERN.fullmatch(counter):
                    raise CounterRuntimeError("COUNTER_STATE_ERROR", "الگوی شماره نامعتبر است.")
                self._metrics.record_alloc("success")
                if attempt > 1:
                    self._metrics.record_retry("counter_allocate", attempts=attempt - 1)
                return CounterResult(counter=counter, year_code=normalized["year_code"], status="new")
            if status == "REUSED":
                counter = result["counter"]
                if not COUNTER_PATTERN.fullmatch(counter):
                    raise CounterRuntimeError("COUNTER_STATE_ERROR", "الگوی شماره نامعتبر است.")
                self._metrics.record_alloc("reused")
                if attempt > 1:
                    self._metrics.record_retry("counter_allocate", attempts=attempt - 1)
                return CounterResult(counter=counter, year_code=normalized["year_code"], status="reused")
            if status == "PENDING":
                if attempt == self._wait_attempts:
                    break
                self._metrics.record_retry("counter_allocate")
                await self._executor.sleep(min(backoff, self._wait_max / 1000.0))
                backoff = min(backoff * 2, self._wait_max / 1000.0)
                continue
            if status == "EXHAUSTED":
                self._metrics.record_exhausted(normalized["year_code"], normalized["gender"])
                raise CounterRuntimeError(
                    "COUNTER_EXHAUSTED",
                    "ظرفیت شماره ثبت برای این سال تکمیل شده است.",
                )
            raise CounterRuntimeError(
                "COUNTER_STATE_ERROR",
                "پاسخ نامعتبر از زیرساخت شمارنده دریافت شد.",
                details=json.dumps(result, ensure_ascii=False),
            )

        raise CounterRuntimeError(
            "COUNTER_RETRY_EXHAUSTED",
            "امکان تخصیص شماره ثبت وجود ندارد؛ دوباره تلاش کنید.",
            details=f"attempts={attempts}",
        )


_PENDING_JSON = json.dumps({"status": "PENDING"})

_ALLOCATE_SCRIPT = """
-- counter_allocate
local json = cjson
local student_key = KEYS[1]
local sequence_key = KEYS[2]
local placeholder = ARGV[1]
local year_code = ARGV[2]
local prefix = ARGV[3]
local center = ARGV[4]
local gender = ARGV[5]
local seq_max = tonumber(ARGV[6])
local ttl_ms = tonumber(ARGV[7])

local existing_json = redis.call('GET', student_key)
if existing_json then
    local ok, decoded = pcall(json.decode, existing_json)
    if not ok or decoded == nil then
        return json.encode({status = 'PENDING'})
    end
    if decoded.status == 'PENDING' then
        return json.encode({status = 'PENDING'})
    end
    return json.encode({status = 'REUSED', counter = decoded.counter, serial = decoded.serial})
end

redis.call('SET', student_key, placeholder, 'PX', ttl_ms)
local seq = redis.call('INCR', sequence_key)
if seq > seq_max then
    redis.call('DEL', student_key)
    return json.encode({status = 'EXHAUSTED'})
end
local serial = string.format('%04d', seq)
local counter = year_code .. prefix .. serial
local payload = {status = 'ASSIGNED', counter = counter, center = center, gender = gender, serial = serial, year_code = year_code}
redis.call('SET', student_key, json.encode(payload))
return json.encode({status = 'NEW', counter = counter, serial = serial})
"""


__all__ = ["CounterRuntime", "CounterRuntimeError", "CounterResult"]
