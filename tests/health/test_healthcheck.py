from __future__ import annotations

import importlib
import pathlib
import sys
import types

from fastapi import FastAPI

from sma.repo_doctor.healthcheck import HealthDoctor, MIDDLEWARE_EXPECTED_ORDER
from sma.repo_doctor.clock import tehran_clock
from sma.repo_doctor.logging_utils import JsonLogger
from sma.repo_doctor.metrics import DoctorMetrics
from sma.repo_doctor.retry import RetryPolicy


class RateLimit:
    pass


class Idempotency:
    pass


class Auth:
    pass


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimit)
    app.add_middleware(Idempotency)
    app.add_middleware(Auth)

    @app.get("/ping")
    def ping():
        return {"status": "ok"}

    return app


def test_health_creates_shim_and_validates(tmp_path: pathlib.Path, monkeypatch) -> None:
    src_dir = tmp_path / "src" / "phase2_uploads"
    src_dir.mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "app.py").write_text(
        "from fastapi import FastAPI\n\n\n"
        "from tests.health.test_healthcheck import build_app\n\n\n"
        "def create_app():\n    return build_app()\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    src_module = types.ModuleType("src")
    src_module.__path__ = [str(tmp_path / "src")]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src", src_module)

    doctor = HealthDoctor(
        root=tmp_path,
        apply=True,
        logger=JsonLogger(tmp_path / "reports" / "health.ndjson", tehran_clock()),
        metrics=DoctorMetrics(tmp_path / "reports" / "health.prom"),
        retry=RetryPolicy(),
        clock=tehran_clock(),
    )

    report = doctor.check()
    assert report.metrics["middleware_order"][:3] == MIDDLEWARE_EXPECTED_ORDER

    shim_path = tmp_path / "src" / "main.py"
    assert shim_path.exists()

    sys.modules.pop("sma.main", None)
    module = importlib.import_module("sma.main")
    assert hasattr(module, "app")
