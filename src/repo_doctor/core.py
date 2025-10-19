from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Iterable, List

from .clock import Clock, tehran_clock
from .deps import DependencyDoctor
from .envfile import EnvDoctor
from .healthcheck import HealthDoctor
from .imports import ImportDoctor
from .logging_utils import JsonLogger
from .metrics import DoctorMetrics
from .report import DoctorRunReport
from .retry import RetryPolicy
from .state import DebugBundle


@dataclass(slots=True)
class DoctorConfig:
    root: pathlib.Path
    apply: bool = False
    clock: Clock = field(default_factory=tehran_clock)
    report_dir: pathlib.Path | None = None


class RepoDoctor:
    """High level orchestration for repo remediation routines."""

    def __init__(self, config: DoctorConfig) -> None:
        self.config = config
        self.root = config.root
        self.apply = config.apply
        self.clock = config.clock
        self.report_dir = config.report_dir or self.root / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.logger = JsonLogger(self.report_dir / "doctor.ndjson", self.clock)
        self.metrics = DoctorMetrics(self.report_dir / "doctor.prom")
        self.retry_policy = RetryPolicy()
        self.debug_bundle = DebugBundle(self.report_dir / "doctor_debug.json", self.clock)

        self.import_doctor = ImportDoctor(
            root=self.root,
            apply=self.apply,
            logger=self.logger,
            metrics=self.metrics,
            retry=self.retry_policy,
            debug=self.debug_bundle,
        )
        self.dependency_doctor = DependencyDoctor(
            root=self.root,
            apply=self.apply,
            logger=self.logger,
            metrics=self.metrics,
            retry=self.retry_policy,
            clock=self.clock,
        )
        self.env_doctor = EnvDoctor(
            root=self.root,
            apply=self.apply,
            logger=self.logger,
            retry=self.retry_policy,
        )
        self.health_doctor = HealthDoctor(
            root=self.root,
            apply=self.apply,
            logger=self.logger,
            metrics=self.metrics,
            retry=self.retry_policy,
            clock=self.clock,
        )

    # ------------------------------------------------------------------
    def scan(self) -> DoctorRunReport:
        """Perform a dry-run import scan."""

        return self.import_doctor.scan()

    def fix(self) -> DoctorRunReport:
        """Apply import fixes and env hygiene."""

        fixes = self.import_doctor.scan()
        if self.apply:
            self.import_doctor.apply(fixes)
            self.env_doctor.ensure()
        return fixes

    def deps(self) -> DoctorRunReport:
        """Generate runtime dependencies and probe environment."""

        return self.dependency_doctor.ensure()

    def health(self) -> DoctorRunReport:
        """Run deterministic health check for FastAPI."""

        return self.health_doctor.check()

    def run_all(self) -> List[DoctorRunReport]:
        tasks: Iterable[DoctorRunReport] = (
            self.scan(),
            self.deps(),
            self.health(),
        )
        return list(tasks)

    # ------------------------------------------------------------------
    def export_bundle(self) -> None:
        bundle = {
            "apply": self.apply,
            "reports": [report.as_dict() for report in self.run_all()],
        }
        self.debug_bundle.record("summary", bundle)
        self.debug_bundle.flush()
        self.logger.flush()
        self.metrics.flush()


__all__ = ["RepoDoctor", "DoctorConfig"]
