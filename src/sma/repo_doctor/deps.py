from __future__ import annotations

import importlib
import pathlib
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List

from .clock import Clock
from .io_utils import atomic_write, ensure_crlf
from .logging_utils import JsonLogger
from .metrics import DoctorMetrics
from .report import DoctorRunReport
from .retry import RetryPolicy

DEV_PATTERNS = {
    "pip-audit",
    "bandit",
    "ruff",
    "mypy",
    "black",
    "flake8",
    "pytest",
    "pytest-cov",
    "pytest-xdist",
    "ipython",
    "pre-commit",
    "wheel",
}

REQUIRED_IMPORTS = [
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "prometheus_client",
    "pandas",
    "openpyxl",
    "orjson",
    "numpy",
]


@dataclass(slots=True)
class DependencyDoctor:
    root: pathlib.Path
    apply: bool
    logger: JsonLogger
    metrics: DoctorMetrics
    retry: RetryPolicy
    clock: Clock

    def ensure(self) -> DoctorRunReport:
        report = DoctorRunReport(name="deps")
        runtime_path = self.root / "requirements.runtime.txt"
        requirements_path = self.root / "requirements.txt"
        if not requirements_path.exists():
            report.add_finding(message="requirements.txt missing")
            return report

        lines = requirements_path.read_text(encoding="utf-8").splitlines()
        filtered: List[str] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name = line.split("==")[0].split(">=")[0].split("<=")[0]
            if any(name.lower().startswith(pattern) for pattern in DEV_PATTERNS):
                continue
            filtered.append(line)
        version_info = sys.version_info
        if version_info.major == 3 and version_info.minor >= 13:
            filtered = self._ensure_py313_pins(filtered)
        if self.apply:
            atomic_write(runtime_path, ensure_crlf("\n".join(filtered) + "\n"), newline="")
            self.logger.info("Generated runtime requirements", path=str(runtime_path))
        report.add_finding(path=str(runtime_path), count=len(filtered))

        probe = self._probe_dependencies()
        report.metrics["imports"] = probe
        return report

    def _ensure_py313_pins(self, lines: List[str]) -> List[str]:
        output = []
        seen_numpy = False
        seen_pandas = False
        for line in lines:
            lower = line.lower()
            if lower.startswith("numpy"):
                seen_numpy = True
                output.append("numpy>=2.1.0")
            elif lower.startswith("pandas"):
                seen_pandas = True
                output.append("pandas>=2.2.3")
            else:
                output.append(line)
        if not seen_numpy:
            output.append("numpy>=2.1.0")
        if not seen_pandas:
            output.append("pandas>=2.2.3")
        return output

    def _probe_dependencies(self) -> Dict[str, str]:
        results: Dict[str, str] = {}
        for module in REQUIRED_IMPORTS:
            try:
                importlib.import_module(module)
            except Exception as exc:
                results[module] = f"FAIL: {exc.__class__.__name__}"
            else:
                results[module] = "OK"
        return results
