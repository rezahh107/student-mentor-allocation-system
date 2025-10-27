#!/usr/bin/env python3
"""Deterministic pytest orchestrator with Strict Scoring v2 compliance."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    import redis.asyncio as redis_async  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    redis_async = None  # type: ignore

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - optional dependency.
    CollectorRegistry = None  # type: ignore
    Counter = None  # type: ignore
    Histogram = None  # type: ignore

try:
    from tools import mw_probe
except ModuleNotFoundError:  # pragma: no cover - defensive in stripped installs.
    mw_probe = None  # type: ignore

from tools.strict_score_core import (
    EvidenceMatrix,
    ScoreEngine,
    build_quality_report,
    detect_repo_features,
    gather_quality_validations,
    merge_feature_sources,
    scan_todo_markers,
)
from tools.strict_score_reporter import (
    StrictMetadata,
    StrictScoreLogger as StrictWriterLogger,
    StrictScoreMetrics,
    StrictScoreWriter,
    build_real_payload_from_score,
    parse_pytest_summary_extended,
)

class DeterministicClock:
    """Deterministic clock that never touches the wall clock."""

    def __init__(self, seed: str) -> None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self._rng = random.Random(digest)
        self._counter = 0

    def iso(self) -> str:
        self._counter += 1
        minute = self._counter % 60
        hour = (self._counter // 60) % 24
        day = 1 + ((self._counter // (60 * 24)) % 28)
        return f"1402-01-{day:02d}T{hour:02d}:{minute:02d}:00+03:30"

    def jittered_duration(self) -> float:
        base = 0.01 + self._rng.random() * 0.05
        jitter = self._rng.random() * 0.02
        return round(base + jitter, 6)


class JsonLogger:
    """Structured JSON logger with correlation ID and deterministic timestamps."""

    def __init__(self, stream, clock: DeterministicClock, correlation_id: str) -> None:
        self._stream = stream
        self._clock = clock
        self._cid = correlation_id

    def _emit(self, level: str, message: str, **fields: Any) -> None:
        payload = {
            "ts": self._clock.iso(),
            "level": level,
            "message": message,
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

    def info(self, message: str, **fields: Any) -> None:
        self._emit("INFO", message, **fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit("WARNING", message, **fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit("ERROR", message, **fields)


class PrometheusFacade:
    """Optional Prometheus metrics for orchestrator observability."""

    def __init__(self) -> None:
        self._available = not (
            CollectorRegistry is None or Counter is None or Histogram is None
        )
        self.registry = None
        self.retry_counter = None
        self.exhaust_counter = None
        self.duration_hist = None
        self._initialise_metrics()

    def _initialise_metrics(self) -> None:
        if not self._available:  # pragma: no cover - metrics library absent.
            self.registry = None
            self.retry_counter = None
            self.exhaust_counter = None
            self.duration_hist = None
            return

        self.registry = CollectorRegistry()
        self.retry_counter = Counter(
            "orchestrator_retries_total",
            "Total retries issued by orchestrator",
            ("stage",),
            registry=self.registry,
        )
        self.exhaust_counter = Counter(
            "orchestrator_exhaustion_total",
            "Retry loops exhausted by orchestrator",
            ("stage",),
            registry=self.registry,
        )
        self.duration_hist = Histogram(
            "orchestrator_stage_duration_seconds",
            "Synthetic duration samples recorded by orchestrator",
            ("stage",),
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.2, 0.5),
        )

    def observe_retry(self, stage: str) -> None:
        if self.retry_counter is not None:
            self.retry_counter.labels(stage=stage).inc()

    def observe_exhaustion(self, stage: str) -> None:
        if self.exhaust_counter is not None:
            self.exhaust_counter.labels(stage=stage).inc()

    def observe_duration(self, stage: str, duration: float) -> None:
        if self.duration_hist is not None:
            self.duration_hist.labels(stage=stage).observe(duration)

    def reset(self) -> None:
        """Recreate the registry so each run starts from a clean slate."""

        self._initialise_metrics()


@dataclasses.dataclass
class PytestResult:
    returncode: int
    summary: Dict[str, int]
    tail: List[str]


class StateManager:
    """Controls Redis flush, RateLimit env snapshots, and CollectorRegistry reset."""

    def __init__(
        self,
        mode: str,
        flush_flag: str,
        logger: JsonLogger,
        metrics: PrometheusFacade,
    ) -> None:
        self.mode = mode
        self.flush_flag = flush_flag
        self.logger = logger
        self.metrics = metrics
        self.redis_status = "skipped"
        self.redis_error: Optional[str] = None
        self._rate_snapshot = self._snapshot_rate_limit_env()

    def _snapshot_rate_limit_env(self) -> Dict[str, str]:
        prefix = "IMPORT_TO_SABT_RATELIMIT_"
        return {key: value for key, value in os.environ.items() if key.startswith(prefix)}

    def should_flush_redis(self) -> bool:
        if self.flush_flag == "yes":
            return True
        if self.flush_flag == "no":
            return False
        if self.mode == "redisless":
            return False
        if self.mode == "redis":
            return True
        return redis_async is not None

    async def _flush(self) -> None:
        if redis_async is None:
            raise RuntimeError("redis library not installed")
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis_async.from_url(url, encoding="utf-8", decode_responses=True)
        try:
            await client.flushdb()
        finally:
            await client.close()

    def flush_before(self) -> None:
        if not self.should_flush_redis():
            self.logger.info("state.redis.skip", mode=self.mode, flush=self.flush_flag)
            return
        try:
            asyncio.run(self._flush())
            self.redis_status = "flushed"
            self.logger.info("state.redis.flushed", stage="pre")
        except Exception as exc:  # pragma: no cover - depends on environment.
            self.metrics.observe_exhaustion("redis_pre")
            self.redis_status = "unavailable"
            self.redis_error = "«سرویس Redis در دسترس نیست؛ اجرای تست‌ها ادامه یافت (حالت محدود).»"
            self.logger.error("state.redis.error", error=str(exc))

    def flush_after(self) -> None:
        if self.redis_status != "flushed":
            return
        try:
            asyncio.run(self._flush())
            self.logger.info("state.redis.flushed", stage="post")
        except Exception as exc:  # pragma: no cover
            self.metrics.observe_retry("redis_post")
            self.logger.warning("state.redis.cleanup_failed", error=str(exc))

    def restore_rate_limit_env(self) -> None:
        prefix = "IMPORT_TO_SABT_RATELIMIT_"
        for key in list(os.environ.keys()):
            if key.startswith(prefix):
                os.environ.pop(key, None)
        for key, value in self._rate_snapshot.items():
            os.environ[key] = value

    def reset_prometheus_registry(self) -> None:
        self.metrics.reset()

    def prepare(self) -> None:
        self.flush_before()
        self.reset_prometheus_registry()

    def finalize(self) -> None:
        self.flush_after()
        self.restore_rate_limit_env()
        self.reset_prometheus_registry()


class PytestRunner:
    """Executes pytest exactly once with warnings treated as errors."""

    def __init__(
        self,
        args: argparse.Namespace,
        logger: JsonLogger,
        metrics: PrometheusFacade,
        clock: DeterministicClock,
    ) -> None:
        self.args = args
        self.logger = logger
        self.metrics = metrics
        self.clock = clock

    def _command(self) -> List[str]:
        cmd = [sys.executable, "-m", "pytest", "-W", "error"]
        if self.args.k:
            cmd.extend(["-k", self.args.k])
        if self.args.maxfail is not None:
            cmd.append(f"--maxfail={self.args.maxfail}")
        if self.args.junitxml:
            cmd.append(f"--junitxml={self.args.junitxml}")
        return cmd

    def run(self) -> PytestResult:
        command = self._command()
        env = os.environ.copy()
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        env.setdefault("PYTHONWARNINGS", "error")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("MPLBACKEND", "Agg")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        if self.args.mode == "redis":
            env["PYTEST_REDIS"] = "1"
            env.pop("TEST_REDIS_STUB", None)
        elif self.args.mode == "redisless":
            env["TEST_REDIS_STUB"] = "1"
            env.pop("PYTEST_REDIS", None)
        elif "PYTEST_REDIS" not in env and "TEST_REDIS_STUB" not in env:
            env["TEST_REDIS_STUB"] = "1"
        self.logger.info("pytest.start", command=" ".join(command))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdout is not None
        tail: deque[str] = deque(maxlen=60)
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line.rstrip("\n"))
        process.wait()
        captured = "\n".join(tail)
        summary, found = parse_pytest_summary_extended(captured)
        if not found:
            raise RuntimeError("Pytest summary not found in output. Use -vv for diagnostics.")
        summary_path = Path(os.environ.get("PYTEST_SUMMARY_PATH", "reports/pytest-summary.txt"))
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_line = (
            "= "
            f"{summary.get('passed', 0)} passed, "
            f"{summary.get('failed', 0)} failed, "
            f"{summary.get('skipped', 0)} skipped, "
            f"{summary.get('xfailed', 0)} xfailed, "
            f"{summary.get('xpassed', 0)} xpassed, "
            f"{summary.get('errors', 0)} errors, "
            f"{summary.get('warnings', 0)} warnings ="
        )
        summary_path.write_text(summary_line + "\n", encoding="utf-8")
        self.logger.info("pytest.finish", returncode=process.returncode, summary=summary)
        return PytestResult(returncode=process.returncode, summary=summary, tail=list(tail))


def collect_p95_samples(clock: DeterministicClock, metrics: PrometheusFacade, sample_count: int) -> List[float]:
    samples: List[float] = []
    for _ in range(max(0, sample_count)):
        duration = clock.jittered_duration()
        samples.append(duration)
        metrics.observe_duration("orchestrator", duration)
    return samples


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict Scoring v2 pytest orchestrator")
    parser.add_argument("--k", dest="k", help="pytest -k expression")
    parser.add_argument("--maxfail", type=int, default=None, help="maximum failures before pytest aborts")
    parser.add_argument("--mode", choices=["auto", "redisless", "redis"], default="auto", help="Environment mode")
    parser.add_argument("--flush-redis", choices=["auto", "yes", "no"], default="auto", help="Force Redis flush behaviour")
    parser.add_argument("--probe-mw-order", choices=["auto", "no"], default="auto", help="Optionally probe middleware order")
    parser.add_argument("--p95-samples", type=int, default=5, help="Synthetic duration samples for p95 reporting")
    parser.add_argument("--json", dest="json_path", help="Write strict score JSON output")
    parser.add_argument("--junitxml", help="Forward to pytest --junitxml")
    parser.add_argument("--evidence-map", dest="evidence_map", help="Evidence map file (json/md)")
    parser.add_argument("--clock-seed", default="ci", help="Deterministic seed for timestamps")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path.cwd()
    clock = DeterministicClock(args.clock_seed)
    correlation_id = hashlib.sha256(f"{repo_root}:{args.clock_seed}".encode("utf-8")).hexdigest()[:16]
    logger = JsonLogger(sys.stderr, clock, correlation_id)
    metrics = PrometheusFacade()
    state = StateManager(args.mode, args.flush_redis, logger, metrics)

    evidence = EvidenceMatrix()
    if args.evidence_map:
        evidence_path = Path(args.evidence_map)
        if evidence_path.exists():
            evidence.load(evidence_path)
        else:
            logger.warning("evidence.missing", path=str(evidence_path))

    detected_features = detect_repo_features(repo_root)
    features = merge_feature_sources(detected=detected_features, evidence=evidence)
    probe_result: Optional[Tuple[bool, Dict[str, Any]]] = None
    if args.probe_mw_order != "no":
        if mw_probe is None:
            logger.warning("middleware.probe.unavailable", reason="mw_probe module missing")
        else:
            try:
                force = args.probe_mw_order != "auto"
                probe_success, probe_details = mw_probe.probe_and_validate(force=force)
                probe_result = (probe_success, probe_details)
                features["middleware_order"] = bool(features.get("middleware_order", False) or probe_success)
                features["rate_limit_awareness"] = bool(features.get("rate_limit_awareness", False) or probe_success)
                logger.info(
                    "middleware.probe.result",
                    success=probe_success,
                    details=probe_details,
                )
            except Exception as exc:  # pragma: no cover - defensive guard.
                probe_result = (False, {"message": f"mw_probe exception: {exc}"})
                features["middleware_order"] = False
                features["rate_limit_awareness"] = False
                logger.error("middleware.probe.error", error=str(exc))
    todo_count = scan_todo_markers(repo_root)

    state.prepare()
    collect_p95_samples(clock, metrics, args.p95_samples)

    summary = {"passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "warnings": 0, "xpassed": 0}
    pytest_result: Optional[PytestResult] = None
    exit_code = 0
    try:
        runner = PytestRunner(args, logger, metrics, clock)
        pytest_result = runner.run()
        summary = pytest_result.summary
        exit_code = pytest_result.returncode
    except Exception as exc:  # pragma: no cover - orchestrator failure path.
        logger.error("pytest.run.failed", error=str(exc))
        exit_code = 1
    finally:
        state.finalize()

    score_engine = ScoreEngine(gui_in_scope=features.get("gui_scope", False), evidence=evidence)
    spec_statuses = score_engine.apply_evidence_matrix()
    score_engine.apply_feature_flags(features)
    if probe_result is not None:
        success, details = probe_result
        message = details.get("message") if isinstance(details, Mapping) else None
        score_engine.apply_middleware_probe(success=success, message=message)
    score_engine.apply_todo_count(todo_count)
    score_engine.apply_pytest_result(summary=summary, returncode=exit_code)
    score_engine.apply_state(redis_error=state.redis_error)
    score = score_engine.finalize()

    pythonwarnings = os.environ.get("PYTHONWARNINGS", "")
    target_path = Path(args.json_path) if args.json_path else Path("reports/strict_score.json")
    metadata = StrictMetadata(
        phase="test",
        correlation_id=correlation_id,
        clock_seed=args.clock_seed,
        path=target_path,
        pythonwarnings=pythonwarnings,
    )
    payload = build_real_payload_from_score(
        score=score,
        summary=summary,
        metadata=metadata,
        evidence_matrix=evidence,
        spec_statuses=spec_statuses,
    )
    validations = gather_quality_validations(
        report_path=target_path if args.json_path else None,
        payload=payload,
        pythonwarnings=pythonwarnings,
    )
    report = build_quality_report(
        payload=payload,
        evidence=evidence,
        features=features,
        validations=validations,
    )
    print(report)

    if args.json_path:
        strict_logger = StrictWriterLogger(stream=sys.stderr, correlation_id=correlation_id, clock=clock)
        strict_metrics = StrictScoreMetrics()
        StrictScoreWriter(logger=strict_logger, metrics=strict_metrics).write(
            path=target_path,
            payload=payload,
            mode="real",
        )

    if exit_code == 0 and (score.total < 90 or score.caps):
        return 1
    return exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
