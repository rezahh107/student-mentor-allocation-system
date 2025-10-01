from __future__ import annotations

import asyncio
import json
import math
import os
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "IntegrationContext",
    "create_large_dataset",
    "create_persian_dataset",
]

_FA_DIGIT_SOURCE = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
_FA_DIGIT_TARGET = "0123456789" * 2
_DIGIT_TRANSLATION = str.maketrans(_FA_DIGIT_SOURCE, _FA_DIGIT_TARGET)
_ZERO_WIDTH_TRANSLATION = str.maketrans({
    "\u200c": "",
    "\u200b": "",
    "\ufeff": "",
})
_Y_NORMALIZATION = str.maketrans({"ك": "ک", "ي": "ی"})
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _normalize_text(value: Any) -> str:
    """Normalize Persian text with digit folding and zero-width cleanup."""

    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ZERO_WIDTH_TRANSLATION)
    text = text.translate(_Y_NORMALIZATION)
    text = text.translate(_DIGIT_TRANSLATION)
    return text.strip()


class RedisStub:
    """A deterministic in-memory Redis stub with namespace isolation."""

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._data: dict[str, Any] = {}

    def flushdb(self) -> None:
        self._data.clear()

    def keys(self, pattern: str = "*") -> list[str]:
        # Namespace is enforced in key names; pattern support kept simple.
        return sorted(key for key in self._data.keys() if pattern in {"*", key})

    def set(self, key: str, value: Any) -> None:
        namespaced_key = self.namespaced(key)
        self._data[namespaced_key] = value

    def get(self, key: str) -> Any:
        return self._data.get(self.namespaced(key))

    def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(self.namespaced(key), None)

    def namespaced(self, key: str) -> str:
        return f"{self._namespace}:{key}"


@dataclass
class IntegrationContext:
    """Shared helpers for integration/performance tests with defensive defaults."""

    namespace: str = field(default_factory=lambda: f"ci:{uuid.uuid4().hex}")
    redis: RedisStub = field(init=False)
    rate_limit_state: dict[str, Any] = field(default_factory=dict)
    idempotency_store: dict[str, Any] = field(default_factory=dict)
    middleware_events: list[str] = field(default_factory=list)
    retry_log: list[dict[str, Any]] = field(default_factory=list)
    backoff_schedule: list[float] = field(default_factory=list)
    operation_metrics: list[dict[str, Any]] = field(default_factory=list)
    telemetry: dict[str, Any] = field(init=False)
    _base_time: float = field(default=1_710_000_000.0)
    _time_offset: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.redis = RedisStub(self.namespace)
        self._reset_telemetry()

    # ------------------------------------------------------------------
    # Lifecycle & state management
    # ------------------------------------------------------------------
    def setup(self) -> "IntegrationContext":
        self.clear_state()
        return self

    def teardown(self) -> None:
        self.clear_state()

    def clear_state(self) -> None:
        self.redis.flushdb()
        self.rate_limit_state.clear()
        self.idempotency_store.clear()
        self.middleware_events.clear()
        self.retry_log.clear()
        self.backoff_schedule.clear()
        self.operation_metrics.clear()
        self._time_offset = 0.0
        self._reset_telemetry()

    def _reset_telemetry(self) -> None:
        self.telemetry = {
            "counter_validations": 0,
            "valid_counters": 0,
            "validation_errors": 0,
            "total_validation_time": 0.0,
        }

    def clear_rate_limiters(self) -> None:
        self.rate_limit_state.clear()

    # ------------------------------------------------------------------
    # Deterministic timing utilities
    # ------------------------------------------------------------------
    def current_time(self) -> float:
        return self._base_time + self._time_offset

    def _advance_clock(self, delta: float) -> None:
        self._time_offset += max(delta, 0.0) + 0.0001

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------
    def deterministic_jitter(self, attempt: int) -> float:
        seed = int(self.namespace[-6:], 16)
        return ((attempt * 31 + seed) % 17) / 1000.0

    def call_with_retry(
        self,
        func: Callable[[], Any],
        *,
        max_attempts: int = 3,
        base_delay: float = 0.05,
        label: str | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = func()
                self.retry_log.append({"label": label, "attempt": attempt, "status": "success"})
                return result
            except Exception as exc:  # pragma: no cover - defensive logging path
                last_error = exc
                self.retry_log.append(
                    {"label": label, "attempt": attempt, "status": "error", "error": repr(exc)}
                )
                if attempt == max_attempts:
                    break
                delay = base_delay * (2 ** (attempt - 1)) + self.deterministic_jitter(attempt)
                self.backoff_schedule.append(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("call_with_retry reached an unexpected state")

    async def async_call_with_retry(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        max_attempts: int = 3,
        base_delay: float = 0.05,
        label: str | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = await factory()
                self.retry_log.append({"label": label, "attempt": attempt, "status": "success"})
                return result
            except Exception as exc:  # pragma: no cover - defensive logging path
                last_error = exc
                self.retry_log.append(
                    {"label": label, "attempt": attempt, "status": "error", "error": repr(exc)}
                )
                if attempt == max_attempts:
                    break
                delay = base_delay * (2 ** (attempt - 1)) + self.deterministic_jitter(attempt)
                self.backoff_schedule.append(delay)
                await asyncio.sleep(0)
        if last_error is not None:
            raise last_error
        raise RuntimeError("async_call_with_retry reached an unexpected state")

    # ------------------------------------------------------------------
    # Excel safety helpers
    # ------------------------------------------------------------------
    def ensure_excel_safety(
        self,
        df: pd.DataFrame,
        sensitive_columns: Sequence[str],
    ) -> pd.DataFrame:
        safe_df = df.copy()
        for column in safe_df.columns:
            if pd.api.types.is_object_dtype(safe_df[column]):
                safe_df[column] = safe_df[column].map(_normalize_text)
        for column in sensitive_columns:
            if column not in safe_df.columns:
                continue
            safe_df[column] = safe_df[column].map(self._quote_sensitive_value)
        return safe_df

    def _quote_sensitive_value(self, value: Any) -> str:
        normalized = _normalize_text(value)
        if not normalized:
            return ""
        sanitized = normalized
        if sanitized.startswith("'"):
            sanitized = sanitized.lstrip("'")
        if sanitized.startswith(_FORMULA_PREFIXES):
            sanitized = sanitized
        return f"'{sanitized}"

    def write_dataframe_atomically(
        self,
        df: pd.DataFrame,
        final_path: Path | str,
        *,
        format: str,
        sheet_name: str = "Sheet1",
    ) -> Path:
        final_path = Path(final_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        if format == "xlsx":
            df.to_excel(part_path, index=False, engine="openpyxl", sheet_name=sheet_name)
        elif format == "csv":
            df.to_csv(
                part_path,
                index=False,
                encoding="utf-8-sig",
                lineterminator="\r\n",
            )
        elif format == "json":
            df.to_json(part_path, orient="records", force_ascii=False, indent=2)
        else:  # pragma: no cover - guard against misconfiguration
            raise ValueError(f"Unsupported format: {format}")
        with open(part_path, "rb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, final_path)
        return final_path

    def write_excel_in_chunks(
        self,
        df: pd.DataFrame,
        final_path: Path | str,
        *,
        chunk_size: int = 1000,
        sheet_name: str = "Sheet1",
    ) -> Path:
        final_path = Path(final_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = final_path.with_suffix(final_path.suffix + ".part")
        with pd.ExcelWriter(part_path, engine="openpyxl", mode="w") as writer:
            start_row = 0
            header_written = False
            for start in range(0, len(df), chunk_size):
                chunk = df.iloc[start : start + chunk_size]
                chunk.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    index=False,
                    header=not header_written,
                    startrow=start_row,
                )
                start_row += len(chunk)
                if not header_written and len(chunk) > 0:
                    # Account for the header occupying the first row so subsequent chunks
                    # append after the previous data instead of overwriting the last row.
                    start_row += 1
                    header_written = True
        with open(part_path, "rb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, final_path)
        return final_path

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------
    def get_debug_context(self) -> dict[str, Any]:
        return {
            "redis_keys": self.redis.keys(),
            "rate_limit_state": self.rate_limit_state.copy(),
            "middleware_order": self.middleware_events.copy(),
            "env": os.getenv("GITHUB_ACTIONS", "local"),
            "timestamp": self.current_time(),
            "retry_log": self.retry_log.copy(),
            "backoff_schedule": list(self.backoff_schedule),
        }

    def format_debug(self, message: str, **extra: Any) -> str:
        context = self.get_debug_context()
        context.update(extra)
        return f"{message} | context={json.dumps(context, ensure_ascii=False, default=str)}"

    def register_middleware_event(self, name: str) -> None:
        self.middleware_events.append(name)

    def get_middleware_chain(self) -> list[str]:
        return self.middleware_events.copy()

    def file_stats(self, path: Path) -> dict[str, Any]:
        return {
            "path": str(path),
            "namespace": self.namespace,
            "size_bytes": path.stat().st_size,
        }

    def generate_unique_path(self, directory: Path, *, suffix: str) -> Path:
        return directory / f"{self.namespace}-{uuid.uuid4().hex}{suffix}"

    def generate_idempotency_key(self, label: str) -> str:
        return f"{self.namespace}:{label}:{uuid.uuid4().hex}"

    def create_student_roster_dataset(self) -> list[dict[str, Any]]:
        """Produce deterministic roster samples covering edge cases."""

        long_code = int("9" * 6)
        return [
            {
                "student_id": "stu-special",
                "school_code": 654321,
                "year": 1402,
                "expected_type": 1,
            },
            {
                "student_id": "stu-normal",
                "school_code": 123123,
                "year": 1402,
                "expected_type": 0,
            },
            {
                "student_id": "stu-missing",
                "school_code": None,
                "year": 1402,
                "expected_type": 0,
            },
            {
                "student_id": "stu-other-year",
                "school_code": 654321,
                "year": 1403,
                "expected_type": 0,
            },
            {
                "student_id": "stu-zero",
                "school_code": 0,
                "year": 1402,
                "expected_type": 0,
            },
            {
                "student_id": "stu-long",
                "school_code": long_code,
                "year": 1402,
                "expected_type": 1,
            },
        ]

    def validate_counter_format(
        self,
        counter_type: str,
        value: Any,
        *,
        gender_code: int | None = None,
    ) -> bool:
        """Validate counters via SSOT regex with telemetry and timing."""

        from src.shared.counter_rules import COUNTER_PREFIX_MAP, COUNTER_REGEX

        start_time = time.perf_counter()
        normalized_value = _normalize_text(value)
        try:
            is_valid = bool(COUNTER_REGEX.fullmatch(normalized_value))
            if is_valid and gender_code is not None:
                try:
                    expected_prefix = COUNTER_PREFIX_MAP[int(gender_code)]
                except (KeyError, ValueError):
                    is_valid = False
                else:
                    is_valid = normalized_value[2:5] == expected_prefix
        except Exception:  # pragma: no cover - defensive guard
            self.telemetry["validation_errors"] += 1
            return False
        finally:
            elapsed = time.perf_counter() - start_time
            self.telemetry["counter_validations"] += 1
            self.telemetry["total_validation_time"] += elapsed

        if is_valid:
            self.telemetry["valid_counters"] += 1
        else:
            debug_payload = {
                "counter_type": counter_type,
                "value": normalized_value,
                "gender_code": gender_code,
            }
            self.retry_log.append(
                {"label": f"validate_{counter_type}", "status": "invalid", "debug": debug_payload}
            )
        return is_valid

    def build_request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        from types import SimpleNamespace

        request_headers = {"X-Request-ID": self.generate_idempotency_key("req")}
        if headers:
            request_headers.update(headers)
        return SimpleNamespace(
            headers=request_headers,
            method=method,
            url=SimpleNamespace(path=path),
            state={},
        )

    def measure_operation(self, func: Callable[[], Any], *, label: str) -> dict[str, Any]:
        start = time.perf_counter()
        result = func()
        end = time.perf_counter()
        duration = end - start
        self.operation_metrics.append({"label": label, "duration": duration})
        self._advance_clock(duration)
        return {"result": result, "duration": duration}

    def measure_percentile(self, samples: Sequence[float], percentile: float) -> float:
        return float(np.percentile(samples, percentile))


# ----------------------------------------------------------------------
# Dataset factories
# ----------------------------------------------------------------------

def create_large_dataset(rows: int = 10_000) -> pd.DataFrame:
    rng = np.random.default_rng(seed=2024)
    genders = rng.integers(0, 2, size=rows)
    prefixes = np.where(genders == 0, "373", "357")
    counters = [f"{idx % 90:02d}{prefix}{idx % 10_000:04d}" for idx, prefix in enumerate(prefixes)]
    long_text = "«" + "توضیحات" * 10 + "»"
    values = rng.normal(loc=0.0, scale=1.0, size=rows)
    dataset = pd.DataFrame(
        {
            "student_id": np.arange(rows, dtype=np.int64),
            "gender": genders,
            "national_id": [f"{10_000_000_000 + idx:010d}" for idx in range(rows)],
            "counter": counters,
            "mobile": [f"09{rng.integers(10**8, 10**9 - 1):09d}" for _ in range(rows)],
            "mentor_id": [f"MN-{idx:06d}" for idx in range(rows)],
            "value": values,
            "timestamp": pd.date_range("2024-01-01", periods=rows, freq="h"),
            "category": rng.choice(["A", "B", "C"], size=rows),
            "notes": [long_text for _ in range(rows)],
            "formula_risk": ["=SUM(A1:A2)" if idx % 500 == 0 else "متن معمولی" for idx in range(rows)],
            "mixed_digits": ["۰" if idx % 3 == 0 else "0" for idx in range(rows)],
            "nullable": [None if idx % 2 == 0 else "0" for idx in range(rows)],
        }
    )
    return dataset


def create_persian_dataset() -> pd.DataFrame:
    dates = pd.date_range("2024-03-20", periods=4, freq="D")
    return pd.DataFrame(
        {
            "نام": ["رضا", "علی\u200c", "0", None],
            "شهر": ["تهران", "اصفهان", "شیراز", "مشهد"],
            "مبلغ": [1_000_000, 2_500_000, "۰", 0],
            "تاریخ": dates,
            "یادداشت": [
                "دانش‌آموز ممتاز",
                " نیاز به پیگیری",
                "",  # خالی
                "\u200cمتن با نویسه صفر-عرض",
            ],
        }
    )
