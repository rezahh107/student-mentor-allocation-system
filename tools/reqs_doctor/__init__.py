"""Reqs Doctor package providing requirement remediation utilities."""

import importlib.util
from pathlib import Path

from .clock import DeterministicClock
from .obs import DoctorMetrics

MIDDLEWARE_ORDER = ("RateLimit", "Idempotency", "Auth")
MIDDLEWARE_ORDER_DOC = " → ".join(MIDDLEWARE_ORDER)

__all__ = [
    "DeterministicClock",
    "DoctorMetrics",
    "MIDDLEWARE_ORDER",
    "MIDDLEWARE_ORDER_DOC",
    "app",
]


def _load_cli_app():
    cli_path = Path(__file__).resolve().parent.parent / "reqs_doctor.py"
    spec = importlib.util.spec_from_file_location("tools._reqs_doctor_cli", cli_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("reqs_doctor CLI module not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


app = _load_cli_app()
