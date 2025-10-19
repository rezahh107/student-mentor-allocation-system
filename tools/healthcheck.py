from __future__ import annotations

from src.repo_doctor.healthcheck import HealthDoctor
from src.repo_doctor.core import DoctorConfig
from src.repo_doctor.clock import tehran_clock
from src.repo_doctor.logging_utils import JsonLogger
from src.repo_doctor.metrics import DoctorMetrics
from src.repo_doctor.retry import RetryPolicy
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
