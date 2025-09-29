from __future__ import annotations

import uuid
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Callable, Iterable, Sequence

from tenacity import Retrying, RetryError, RetryCallState, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base

from .atomic import atomic_write_json
from .clock import Clock
from .logging_utils import JSONLogger, persian_error
from .metrics import ReliabilityMetrics


class DeterministicWait(wait_base):
    def __init__(self, base: float, cap: float, jitter: float, seed: str) -> None:
        self.base = base
        self.cap = cap
        self.jitter = jitter
        self.seed = seed

    def __call__(self, retry_state: "RetryCallState") -> float:
        attempt = max(1, retry_state.attempt_number)
        backoff = min(self.cap, self.base * (2 ** (attempt - 1)))
        fingerprint = blake2b(f"{self.seed}:{attempt}".encode("utf-8"), digest_size=8).digest()
        jitter_fraction = int.from_bytes(fingerprint, "big") / float(1 << (8 * len(fingerprint)))
        jitter = jitter_fraction * self.jitter
        return backoff + jitter


class ChaosInjectionError(RuntimeError):
    pass


@dataclass(slots=True)
class ChaosContext:
    scenario: str
    correlation_id: str
    namespace: str


class ChaosScenario:
    def __init__(
        self,
        *,
        name: str,
        metrics: ReliabilityMetrics,
        logger: JSONLogger,
        clock: Clock,
        reports_root: Path,
        max_attempts: int = 5,
        base_backoff: float = 0.05,
        max_backoff: float = 1.0,
        jitter: float = 0.02,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.name = name
        self.metrics = metrics
        self._logger = logger
        self.clock = clock
        self.reports_root = Path(reports_root)
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.jitter = jitter
        self.sleeper = sleeper or (lambda _: None)

    def _retrying(self, correlation_id: str) -> Retrying:
        wait_strategy = DeterministicWait(
            base=self.base_backoff,
            cap=self.max_backoff,
            jitter=self.jitter,
            seed=correlation_id,
        )
        return Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_strategy,
            sleep=self.sleeper,
            retry=retry_if_exception_type((ChaosInjectionError, ConnectionError)),
            reraise=True,
        )

    def run(
        self,
        operation: Callable[[], object],
        *,
        fault_plan: Sequence[int] | Iterable[int] | None = None,
        correlation_id: str | None = None,
        namespace: str = "default",
    ) -> dict[str, object]:
        corr = correlation_id or uuid.uuid4().hex
        logger = self._logger.bind(corr)
        plan = list(fault_plan or ())
        retrying = self._retrying(corr)
        attempts = 0
        injected = 0
        last_error: str | None = None
        start = self.clock.now()
        try:
            for attempt in retrying:
                attempts = attempt.retry_state.attempt_number
                with attempt:
                    if attempts <= len(plan) and plan[attempts - 1]:
                        injected += 1
                        last_error = "Injected fault"
                        self.metrics.mark_chaos(
                            scenario=self.name,
                            incident_type=self._incident_type,
                            outcome="fault",
                            reason="injected_fault",
                            namespace=namespace,
                        )
                        self.metrics.mark_retry(
                            operation=f"chaos:{self.name}",
                            namespace=namespace,
                        )
                        logger.warning(
                            f"chaos.retry.{self.name}",
                            attempt=attempts,
                            last_error=last_error,
                            namespace=namespace,
                            plan_index=attempts - 1,
                        )
                        raise ChaosInjectionError(last_error)
                    try:
                        result = operation()
                    except ConnectionError as exc:
                        last_error = str(exc)
                        self.metrics.mark_retry(
                            operation=f"chaos:{self.name}",
                            namespace=namespace,
                        )
                        logger.warning(
                            f"chaos.retry.{self.name}",
                            attempt=attempts,
                            last_error=last_error,
                            namespace=namespace,
                            plan_index=attempts - 1,
                        )
                        raise
                    self.metrics.mark_chaos(
                        scenario=self.name,
                        incident_type=self._incident_type,
                        outcome="success",
                        reason="completed",
                        namespace=namespace,
                    )
                    self.metrics.mark_operation(
                        operation=f"chaos:{self.name}",
                        outcome="success",
                        reason="completed",
                        namespace=namespace,
                    )
                    report = self._build_report(
                        attempts=attempts,
                        injected=injected,
                        success=True,
                        last_error=None,
                        start=start,
                        namespace=namespace,
                    )
                    if result is not None:
                        report["result"] = result
                    self._write_report(report)
                    return report
        except RetryError as err:
            last_error = str(err)
            self.metrics.mark_exhausted(
                operation=f"chaos:{self.name}", namespace=namespace
            )
            self.metrics.mark_operation(
                operation=f"chaos:{self.name}",
                outcome="failure",
                reason="exhausted",
                namespace=namespace,
            )
            logger.error(
                f"chaos.exhausted.{self.name}",
                attempts=attempts,
                last_error=last_error,
                namespace=namespace,
            )
            report = self._build_report(
                attempts=attempts,
                injected=injected,
                success=False,
                last_error=last_error,
                start=start,
                namespace=namespace,
            )
            self._write_report(report)
            raise RuntimeError(
                persian_error(
                    "آزمایش آشوب در نهایت موفق نشد؛ لطفاً دوباره تلاش کنید.",
                    "CHAOS_FAILURE",
                    correlation_id=corr,
                        )
                )
        report = self._build_report(
            attempts=attempts,
            injected=injected,
            success=False,
            last_error=last_error,
            start=start,
            namespace=namespace,
        )
        self._write_report(report)
        return report

    @property
    def _incident_type(self) -> str:
        return "redis" if isinstance(self, RedisFlapScenario) else "postgres"

    def _build_report(
        self,
        *,
        attempts: int,
        injected: int,
        success: bool,
        last_error: str | None,
        start: object,
        namespace: str,
    ) -> dict[str, object]:
        end = self.clock.now()
        duration = max(0.0, (end - start).total_seconds())
        return {
            "scenario": self.name,
            "attempts": attempts,
            "injected": injected,
            "success": success,
            "last_error": last_error,
            "started_at": getattr(start, "isoformat", lambda: str(start))(),
            "ended_at": end.isoformat(),
            "duration_s": duration,
            "namespace": namespace,
        }

    def _write_report(self, report: dict[str, object]) -> None:
        destination = self.reports_root / f"{self.name}.json"
        atomic_write_json(destination, report)


class RedisFlapScenario(ChaosScenario):
    pass


class PostgresConnectionResetScenario(ChaosScenario):
    pass


class RedisFlapInjector(RedisFlapScenario):
    """Backwards compatible alias emphasising injector semantics."""


class DbConnectionResetInjector(PostgresConnectionResetScenario):
    """Backwards compatible alias emphasising injector semantics."""


__all__ = [
    "RedisFlapScenario",
    "PostgresConnectionResetScenario",
    "RedisFlapInjector",
    "DbConnectionResetInjector",
    "ChaosInjectionError",
]
