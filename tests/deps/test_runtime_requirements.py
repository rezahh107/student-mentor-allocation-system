from __future__ import annotations

import pathlib
import sys

from src.repo_doctor.deps import DependencyDoctor
from src.repo_doctor.clock import tehran_clock
from src.repo_doctor.core import DoctorConfig
from src.repo_doctor.logging_utils import JsonLogger
from src.repo_doctor.metrics import DoctorMetrics
from src.repo_doctor.retry import RetryPolicy


def build_doctor(tmp_path: pathlib.Path, apply: bool = True) -> DependencyDoctor:
    config = DoctorConfig(root=tmp_path, apply=apply, clock=tehran_clock())
    return DependencyDoctor(
        root=config.root,
        apply=config.apply,
        logger=JsonLogger(tmp_path / "reports" / "deps.ndjson", config.clock),
        metrics=DoctorMetrics(tmp_path / "reports" / "deps.prom"),
        retry=RetryPolicy(),
        clock=config.clock,
    )


def test_generates_runtime_requirements(tmp_path: pathlib.Path, monkeypatch) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "\n".join([
            "fastapi==0.111.0",
            "pip-audit==2.5.0",
            "numpy==1.26.0",
            "pandas==2.1.0",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "version_info", type("V", (), {"major": 3, "minor": 13})())
    doctor = build_doctor(tmp_path, apply=True)
    report = doctor.ensure()

    runtime = (tmp_path / "requirements.runtime.txt").read_text(encoding="utf-8")
    assert "numpy>=2.1.0" in runtime
    assert "pandas>=2.2.3" in runtime
    assert "pip-audit" not in runtime

    assert report.metrics["imports"]["fastapi"] == "OK"
