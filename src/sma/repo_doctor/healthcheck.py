from __future__ import annotations

import importlib
import pathlib
from dataclasses import dataclass

from fastapi import FastAPI
from sma._local_uvicorn import Config

from .clock import Clock
from .io_utils import atomic_write
from .logging_utils import JsonLogger
from .metrics import DoctorMetrics
from .report import DoctorRunReport
from .retry import RetryPolicy

MIDDLEWARE_EXPECTED_ORDER = ["RateLimit", "Idempotency", "Auth"]


@dataclass(slots=True)
class HealthDoctor:
    root: pathlib.Path
    apply: bool
    logger: JsonLogger
    metrics: DoctorMetrics
    retry: RetryPolicy
    clock: Clock

    def check(self) -> DoctorRunReport:
        report = DoctorRunReport(name="health")
        shim_created = self._ensure_main_shim()
        report.metrics["shim_created"] = shim_created
        app = self._load_app()
        report.metrics["middleware_order"] = self._middleware_order(app)
        self._dry_run_uvicorn(app)
        return report

    def _ensure_main_shim(self) -> bool:
        shim_path = self.root / "src" / "main.py"
        if shim_path.exists():
            return False
        if not self.apply:
            self.logger.warning("src/main.py missing (dry-run)")
            return False
        content = (
            "from sma.phase2_uploads.app import create_app\r\n"
            "app = create_app()\r\n"
        )
        atomic_write(shim_path, content, newline="")
        self.logger.info("Created FastAPI shim", path=str(shim_path))
        return True

    def _load_app(self) -> FastAPI:
        module = importlib.import_module("sma.main")
        app = getattr(module, "app", None)
        if not isinstance(app, FastAPI):
            raise RuntimeError("sma.main:app not found")
        return app

    def _middleware_order(self, app: FastAPI) -> list[str]:
        registered = [mw.cls.__name__ for mw in app.user_middleware]
        order = list(reversed(registered))
        if order[:3] != MIDDLEWARE_EXPECTED_ORDER:
            raise AssertionError(
                "ترتیب میان‌افزار نامعتبر است؛ باید RateLimit → Idempotency → Auth باشد."
            )
        return order

    def _dry_run_uvicorn(self, app: FastAPI) -> None:
        config = Config(app=app, host="127.0.0.1", port=0, lifespan="off", loop="asyncio")
        config.load()
        self.logger.info("Health check configuration prepared", loop=config.loop)
