"""Shared utilities for deterministic strict score reporting in CI."""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import orjson

try:  # Optional dependency, mocked within tests when unavailable
    from prometheus_client import CollectorRegistry, Counter
except Exception:  # pragma: no cover - metrics optional in some environments
    CollectorRegistry = None  # type: ignore
    Counter = None  # type: ignore

SUMMARY_LINE_RE = re.compile(r"=+\s(?P<body>[^=]+?)\s=+")
SUMMARY_PART_RE = re.compile(
    r"(?P<count>[0-9۰-۹٠-٩]+)\s+(?P<label>passed|failed|skipped|xfailed|xpassed|warnings?)",
    re.IGNORECASE,
)

ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff", "\u202a", "\u202c"}
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclasses.dataclass(frozen=True)
class StrictMetadata:
    """Metadata describing the current report write."""

    phase: str
    correlation_id: str
    clock_seed: str
    path: Path
    pythonwarnings: str


class DeterministicClock:
    """Generates deterministic Tehran timestamps without touching wall-clock."""

    def __init__(self, seed: str) -> None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self._counter = int.from_bytes(digest[:2], "big") % (60 * 24 * 28)

    def iso(self) -> str:
        self._counter += 1
        minute = self._counter % 60
        hour = (self._counter // 60) % 24
        day = 1 + ((self._counter // (60 * 24)) % 28)
        return f"1402-01-{day:02d}T{hour:02d}:{minute:02d}:00+03:30"


class StrictScoreLogger:
    """Structured JSON logger that masks long fields and injects correlation id."""

    def __init__(self, stream, correlation_id: str, clock: Optional[DeterministicClock] = None) -> None:
        self._stream = stream
        self._cid = correlation_id
        self._clock = clock or DeterministicClock(correlation_id)

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        payload: Dict[str, Any] = {
            "ts": self._clock.iso(),
            "level": level,
            "event": event,
            "correlation_id": self._cid,
        }
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, str) and len(value) > 256:
                payload[key] = value[:253] + "…"
            else:
                payload[key] = value
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()

    def info(self, event: str, **fields: Any) -> None:
        self._emit("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("ERROR", event, **fields)


class StrictScoreMetrics:
    """Prometheus counters required for observability tests."""

    def __init__(self) -> None:
        self.registry = None
        self.created_counter = None
        self.write_error_counter = None
        if CollectorRegistry is None or Counter is None:  # pragma: no cover - optional path
            return
        self.registry = CollectorRegistry()
        self.created_counter = Counter(
            "ci_strict_report_created_total",
            "Number of strict score reports created",
            ("mode",),
            registry=self.registry,
        )
        self.write_error_counter = Counter(
            "ci_strict_report_write_errors_total",
            "Total strict score write errors",
            ("mode",),
            registry=self.registry,
        )

    def observe_created(self, mode: str) -> None:
        if self.created_counter is not None:
            self.created_counter.labels(mode=mode).inc()

    def observe_error(self, mode: str) -> None:
        if self.write_error_counter is not None:
            self.write_error_counter.labels(mode=mode).inc()


def _normalise_text(text: str) -> str:
    folded = text.translate(FA_DIGITS)
    cleaned = []
    for char in folded:
        if char in ZERO_WIDTH:
            continue
        if ord(char) < 32 and char not in {"\n", "\t"}:
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _base_counts() -> Dict[str, int]:
    return {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "warnings": 0,
    }


def parse_pytest_summary_extended(text: Optional[str]) -> Tuple[Dict[str, int], bool]:
    if not text:
        return _base_counts(), False
    normalised = _normalise_text(str(text))
    match = SUMMARY_LINE_RE.search(normalised)
    if not match:
        return _base_counts(), False
    counts = _base_counts()
    found = False
    for part in match.group("body").split(","):
        chunk = part.strip()
        if not chunk:
            continue
        sub = SUMMARY_PART_RE.match(chunk)
        if not sub:
            continue
        count = int(sub.group("count").translate(FA_DIGITS))
        label = sub.group("label").lower()
        if label in ("warning", "warnings"):
            counts["warnings"] = count
        else:
            counts[label] = count
        found = True
    return counts, found


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:  # pragma: no cover - not all FS support directory fsync
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class StrictScoreWriter:
    """Handles atomic JSON writes with fallback to temporary directory."""

    def __init__(self, logger: StrictScoreLogger, metrics: StrictScoreMetrics) -> None:
        self._logger = logger
        self._metrics = metrics

    def _write_bytes(self, path: Path, data: bytes, mode: str) -> None:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        part_path = parent / f".{path.name}.{uuid.uuid4().hex}.part"
        try:
            with open(part_path, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(part_path, path)
            _fsync_directory(parent)
        except OSError as exc:
            try:
                if part_path.exists():
                    part_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            finally:
                pass
            if exc.errno not in {errno.EROFS, errno.EACCES, errno.ENOSPC}:  # pragma: no cover - rare path
                self._metrics.observe_error(mode)
                raise
            self._metrics.observe_error(mode)
            self._logger.warning(
                "strict_report.fallback_temp", error=str(exc), path=str(path), mode=mode
            )
            fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".part")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, path)
                _fsync_directory(path.parent)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    def write(self, path: Path, payload: Mapping[str, Any], mode: str) -> None:
        data = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
        self._write_bytes(path=path, data=data, mode=mode)
        self._metrics.observe_created(mode)
        self._logger.info("strict_report.written", mode=mode, path=str(path), bytes=len(data))


def _reason_caps_from_counts(counts: Mapping[str, int]) -> Tuple[List[Dict[str, Any]], List[str]]:
    caps: List[Dict[str, Any]] = []
    reasons: List[str] = []
    warnings = counts.get("warnings", 0)
    skipped = counts.get("skipped", 0)
    xfailed = counts.get("xfailed", 0)
    if warnings:
        caps.append({"limit": 90, "reason": f"Warnings detected: {warnings}"})
        reasons.append(f"هشدارها مشاهده شد ({warnings})")
    if skipped or xfailed:
        total = skipped + xfailed
        caps.append({"limit": 92, "reason": f"Skipped/xfail detected: {total}"})
        reasons.append(f"تست‌های ردشده یا xfail: {total}")
    return caps, reasons


def build_real_payload_from_counts(*, counts: Mapping[str, int], metadata: StrictMetadata) -> Dict[str, Any]:
    clock = DeterministicClock(metadata.clock_seed)
    total = sum(counts.get(key, 0) for key in ("passed", "failed", "skipped", "xfailed", "xpassed"))
    caps, reasons = _reason_caps_from_counts(counts)
    reason_texts = reasons or ["بدون محدودیت ثبت‌شده"]
    payload: Dict[str, Any] = {
        "version": "2.0",
        "report_mode": "real",
        "phase": metadata.phase,
        "created_at": clock.iso(),
        "correlation_id": metadata.correlation_id,
        "counts": {
            "passed": counts.get("passed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "xfailed": counts.get("xfailed", 0),
            "xpassed": counts.get("xpassed", 0),
            "warnings": counts.get("warnings", 0),
            "total": total,
        },
        "caps": caps,
        "reasons": reason_texts,
        "evidence": {
            "spec": {},
            "integration_count": 0,
        },
        "scorecard": {
            "status": "counts_only",
            "detail": "Pytest summary parsed without orchestrator scorecard",
        },
        "diagnostics": {
            "pythonwarnings": metadata.pythonwarnings,
            "timezone": "Asia/Tehran",
        },
        "metadata": {
            "path": str(metadata.path),
            "clock_seed": metadata.clock_seed,
        },
    }
    if metadata.pythonwarnings not in {"", "default", "error"}:
        payload.setdefault("caps", []).append({
            "limit": 90,
            "reason": f"Invalid PYTHONWARNINGS policy: {metadata.pythonwarnings}",
        })
        payload.setdefault("reasons", []).append("سیاست هشدار پایتون خارج از محدوده است")
    return payload


def build_real_payload_from_score(
    *,
    score: Any,
    summary: Mapping[str, int],
    metadata: StrictMetadata,
    evidence_matrix: Any,
    spec_statuses: Mapping[str, bool],
    mode: str = "real",
    diagnostics_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    clock = DeterministicClock(metadata.clock_seed)
    counts = {
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "xfailed": summary.get("xfailed", 0),
        "xpassed": summary.get("xpassed", 0),
        "warnings": summary.get("warnings", 0),
    }
    total = sum(counts.values()) - counts["warnings"]
    caps = [{"limit": limit, "reason": reason} for limit, reason in getattr(score, "caps", [])]
    reasons = [reason for _, reason in getattr(score, "caps", [])]
    if not reasons:
        reasons = ["None"]
    evidence_payload: Dict[str, List[str]] = {}
    if hasattr(evidence_matrix, "entries"):
        for key, values in evidence_matrix.entries.items():
            evidence_payload[key] = list(values)
    diagnostics = {
        "pythonwarnings": metadata.pythonwarnings,
        "timezone": "Asia/Tehran",
    }
    if diagnostics_override:
        diagnostics.update(diagnostics_override)

    payload: Dict[str, Any] = {
        "version": "2.0",
        "report_mode": mode,
        "phase": metadata.phase,
        "created_at": clock.iso(),
        "correlation_id": metadata.correlation_id,
        "counts": {**counts, "total": total},
        "caps": caps,
        "reasons": reasons,
        "evidence": {
            "spec": evidence_payload,
            "integration_count": getattr(evidence_matrix, "integration_evidence_count", lambda: 0)(),
        },
        "scorecard": {
            "axes": {
                key: {
                    "label": axis.label,
                    "max_points": axis.max_points,
                    "deductions": axis.deductions,
                    "value": axis.value,
                }
                for key, axis in getattr(score, "axes", {}).items()
            },
            "raw_total": getattr(score, "raw_total", 0.0),
            "total": getattr(score, "total", 0.0),
            "level": getattr(score, "level", "Unknown"),
            "deductions": [
                {"axis": axis_label, "amount": amount, "reason": reason}
                for axis_label, amount, reason in getattr(score, "deductions", [])
            ],
            "next_actions": list(getattr(score, "next_actions", [])),
        },
        "spec_statuses": dict(spec_statuses),
        "diagnostics": diagnostics,
        "metadata": {
            "path": str(metadata.path),
            "clock_seed": metadata.clock_seed,
        },
    }
    if metadata.pythonwarnings not in {"", "default", "error"}:
        payload.setdefault("caps", []).append({
            "limit": 90,
            "reason": f"Invalid PYTHONWARNINGS policy: {metadata.pythonwarnings}",
        })
        payload.setdefault("reasons", []).append("سیاست هشدار پایتون خارج از محدوده است")
    return payload


def build_fallback_payload(
    *,
    metadata: StrictMetadata,
    counts: Optional[Mapping[str, int]] = None,
    score: Optional[Any] = None,
    evidence_matrix: Optional[Any] = None,
    spec_statuses: Optional[Mapping[str, bool]] = None,
    message: str = "گزارش pytest در دسترس نبود؛ گزارش جایگزین ساخته شد",
) -> Dict[str, Any]:
    clock = DeterministicClock(metadata.clock_seed)
    summary = counts or _base_counts()
    base_counts = {
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "xfailed": summary.get("xfailed", 0),
        "xpassed": summary.get("xpassed", 0),
        "warnings": summary.get("warnings", 0),
    }
    total = sum(base_counts.values()) - base_counts["warnings"]
    if score is not None:
        payload = build_real_payload_from_score(
            score=score,
            summary=base_counts,
            metadata=metadata,
            evidence_matrix=evidence_matrix or {},
            spec_statuses=spec_statuses or {},
            mode="synth",
            diagnostics_override={"پیام": message, "کد": "STRICT_SCORE_SYNTH"},
        )
        payload.setdefault("reasons", [])
        if not payload["reasons"]:
            payload["reasons"].append("None")
        if message not in payload["reasons"]:
            payload["reasons"].append(message)
        payload.setdefault("caps", [])
        if not any(cap.get("reason") == message for cap in payload["caps"]):
            payload["caps"].append({"limit": 85, "reason": message})
        payload.setdefault("diagnostics", {})
        payload["diagnostics"].setdefault("پیام", message)
        payload["diagnostics"].setdefault("کد", "STRICT_SCORE_SYNTH")
        payload["diagnostics"].setdefault("pythonwarnings", metadata.pythonwarnings)
        payload["diagnostics"].setdefault("timezone", "Asia/Tehran")
        return payload

    cap_reason = message
    payload: Dict[str, Any] = {
        "version": "2.0",
        "report_mode": "synth",
        "phase": metadata.phase,
        "created_at": clock.iso(),
        "correlation_id": metadata.correlation_id,
        "counts": {**base_counts, "total": total},
        "caps": [{"limit": 85, "reason": cap_reason}],
        "reasons": [cap_reason],
        "evidence": {"spec": {}, "integration_count": 0},
        "scorecard": {
            "status": "synthesized",
            "detail": "Pytest summary unavailable; synthetic report issued",
        },
        "diagnostics": {
            "پیام": cap_reason,
            "کد": "STRICT_SCORE_SYNTH",
            "pythonwarnings": metadata.pythonwarnings,
            "timezone": "Asia/Tehran",
        },
        "metadata": {
            "path": str(metadata.path),
            "clock_seed": metadata.clock_seed,
        },
    }
    if spec_statuses:
        payload["spec_statuses"] = dict(spec_statuses)
    if metadata.pythonwarnings not in {"", "default", "error"}:
        payload["caps"].append({
            "limit": 85,
            "reason": f"Invalid PYTHONWARNINGS policy: {metadata.pythonwarnings}",
        })
        payload["reasons"].append("سیاست هشدار پایتون خارج از محدوده است")
    return payload


__all__ = [
    "StrictMetadata",
    "StrictScoreLogger",
    "StrictScoreMetrics",
    "StrictScoreWriter",
    "DeterministicClock",
    "parse_pytest_summary_extended",
    "build_real_payload_from_counts",
    "build_real_payload_from_score",
    "build_fallback_payload",
]
