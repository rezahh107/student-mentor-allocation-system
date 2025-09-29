"""Shared retry/backoff helpers for security tooling in CI."""
from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Tuple, TypeVar
from weakref import WeakKeyDictionary

from prometheus_client import CollectorRegistry, Counter, Histogram, REGISTRY

LOGGER = logging.getLogger("scripts.security_tools")

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry/backoff logic."""

    max_attempts: int = 3
    base_delay: float = 0.2
    backoff_multiplier: float = 2.0
    jitter_ratio: float = 0.1

    def validate(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if self.jitter_ratio < 0:
            raise ValueError("jitter_ratio must be non-negative")


_METRICS: "WeakKeyDictionary[CollectorRegistry, Tuple[Counter, Counter, Histogram, Histogram]]" = WeakKeyDictionary()


def retry_config_from_env(
    *, prefix: str = "SEC_TOOL", logger: logging.Logger | None = None
) -> RetryConfig:
    """Create a :class:`RetryConfig` from environment variables."""

    log = logger or LOGGER

    def _coerce(name: str, default: float, cast: Callable[[str], float]) -> float:
        env_name = f"{prefix}_{name}"
        raw = os.environ.get(env_name)
        if raw is None or not raw.strip():
            return default
        try:
            return cast(raw)
        except ValueError:
            log.warning(
                "SEC_TOOL_RETRY_CONFIG_INVALID: fallback applied",
                extra={"env": env_name, "value": raw},
            )
            return default

    return RetryConfig(
        max_attempts=int(_coerce("MAX_ATTEMPTS", 3, int)),
        base_delay=_coerce("BASE_DELAY", 0.2, float),
        backoff_multiplier=_coerce("BACKOFF", 2.0, float),
        jitter_ratio=_coerce("JITTER", 0.1, float),
    )


def _resolve_registry(registry: CollectorRegistry | None) -> CollectorRegistry:
    return registry or REGISTRY


def _get_metrics(
    *, registry: CollectorRegistry | None = None,
) -> Tuple[Counter, Counter, Histogram, Histogram]:
    resolved = _resolve_registry(registry)
    try:
        return _METRICS[resolved]
    except KeyError:
        attempts = Counter(
            "security_tool_retry_attempts_total",
            "Total execution attempts for security tooling",
            labelnames=("tool",),
            registry=resolved,
        )
        exhausted = Counter(
            "security_tool_retry_exhausted_total",
            "Number of times security tooling retries were exhausted",
            labelnames=("tool",),
            registry=resolved,
        )
        latency = Histogram(
            "security_tool_retry_latency_seconds",
            "Latency of security tooling attempts",
            labelnames=("tool",),
            registry=resolved,
            buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
        )
        sleep_hist = Histogram(
            "security_tool_retry_sleep_seconds",
            "Backoff sleep durations for security tooling",
            labelnames=("tool",),
            registry=resolved,
            buckets=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
        )
        _METRICS[resolved] = (attempts, exhausted, latency, sleep_hist)
        return attempts, exhausted, latency, sleep_hist


def reset_metrics(*, registry: CollectorRegistry | None = None) -> None:
    """Forget cached counters for the provided registry."""

    resolved = _resolve_registry(registry)
    counters = _METRICS.pop(resolved, None)
    if counters:
        for metric in counters:
            try:
                resolved.unregister(metric)
            except KeyError:
                continue


def _deterministic_jitter(*, seed: str, attempt: int) -> float:
    payload = f"{seed}:{attempt}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return (value % (1 << 53)) / float(1 << 53)


def _compute_sleep(
    *,
    attempt: int,
    config: RetryConfig,
    randomizer: Callable[[], float] | None,
    seed: str,
) -> float:
    delay = config.base_delay * math.pow(config.backoff_multiplier, attempt - 1)
    if config.jitter_ratio == 0:
        return delay
    if randomizer is None:
        jitter_factor = _deterministic_jitter(seed=seed, attempt=attempt)
    else:
        jitter_factor = max(0.0, min(1.0, randomizer()))
    jitter = delay * config.jitter_ratio * jitter_factor
    return delay + jitter


def run_with_retry(
    func: Callable[[], T],
    *,
    tool_name: str,
    config: RetryConfig | None = None,
    registry: CollectorRegistry | None = None,
    sleeper: Callable[[float], None] | None = None,
    randomizer: Callable[[], float] | None = None,
    monotonic: Callable[[], float] | None = None,
    logger: logging.Logger | None = None,
) -> T:
    """Execute ``func`` with retry/backoff and metrics accounting."""

    cfg = config or RetryConfig()
    cfg.validate()
    attempts_counter, exhausted_counter, latency_hist, sleep_hist = _get_metrics(registry=registry)
    sleep_fn = sleeper or time.sleep
    rand_fn = randomizer or random.random
    monotonic_fn = monotonic or time.monotonic
    log = logger or LOGGER
    last_error: BaseException | None = None
    jitter_seed = f"{tool_name}:{cfg.max_attempts}:{cfg.base_delay}:{cfg.backoff_multiplier}:{cfg.jitter_ratio}"

    for attempt in range(1, cfg.max_attempts + 1):
        attempts_counter.labels(tool=tool_name).inc()
        start = monotonic_fn()
        try:
            result = func()
            duration = monotonic_fn() - start
            latency_hist.labels(tool=tool_name).observe(duration)
            log.debug(
                "security tool attempt succeeded",
                extra={
                    "tool": tool_name,
                    "attempt": attempt,
                    "duration": duration,
                },
            )
            return result
        except Exception as exc:  # pragma: no cover - re-raised below
            last_error = exc
            duration = monotonic_fn() - start
            latency_hist.labels(tool=tool_name).observe(duration)
            log.warning(
                "security tool attempt failed; scheduling retry",
                extra={
                    "tool": tool_name,
                    "attempt": attempt,
                    "duration": duration,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            if attempt == cfg.max_attempts:
                exhausted_counter.labels(tool=tool_name).inc()
                log.error(
                    "security tool retries exhausted",
                    extra={
                        "tool": tool_name,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                raise
            sleep = _compute_sleep(
                attempt=attempt,
                config=cfg,
                randomizer=rand_fn if randomizer is not None else None,
                seed=jitter_seed,
            )
            sleep_hist.labels(tool=tool_name).observe(sleep)
            log.debug(
                "security tool sleeping before retry",
                extra={
                    "tool": tool_name,
                    "attempt": attempt,
                    "sleep": sleep,
                },
            )
            sleep_fn(sleep)

    if last_error is not None:  # pragma: no cover
        raise last_error
    raise RuntimeError("run_with_retry exited unexpectedly")
