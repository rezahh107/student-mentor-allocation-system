from __future__ import annotations

from sma.repo_doctor.healthcheck import HealthDoctor
from sma.repo_doctor.core import DoctorConfig
from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.logging_utils import JsonLogger
from sma.repo_doctor.metrics import DoctorMetrics
from sma.repo_doctor.retry import RetryPolicy
import pathlib


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    config = DoctorConfig(root=root, apply=True, clock=tehran_clock())
    doctor = HealthDoctor(
        root=config.root,
        apply=config.apply,
        logger=JsonLogger(root / "reports" / "doctor_health.ndjson", config.clock),
        metrics=DoctorMetrics(root / "reports" / "doctor_health.prom"),
        retry=RetryPolicy(),
        clock=config.clock,
    )
    doctor.check()


if __name__ == "__main__":
    main()
