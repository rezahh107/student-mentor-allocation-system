from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

from scripts.deps.ensure_lock import (
    DependencyManager,
    PERSIAN_AGENTS_MISSING,
    PERSIAN_LOCK_MISSING,
    _load_prometheus_bundle,
    _atomic_write,
)

PERSIAN_PYTEST_MISSING = (
    "«پیش‌نیازهای اجرای تست نصب نشده‌اند (pytest/پلاگین‌ها). لطفاً مرحلهٔ Install (constraints-only) را قبل از Run tests اجرا کنید.»"
)
PERSIAN_INSTALL_ORDER = (
    "«پیش‌نیازهای اجرای تست نصب نشده‌اند (pytest/پلاگین‌ها). لطفاً مرحلهٔ Install (constraints-only) را قبل از Run tests اجرا کنید.»"
)


class CiReadyGuard:
    def __init__(
        self,
        root: Path,
        requirements: Sequence[str],
        *,
        metrics_path: Path | None = None,
        persian: bool = False,
    ) -> None:
        self.root = root
        self.requirements = tuple(requirements)
        self.metrics_path = metrics_path or root / "reports" / "ci-ready.prom"
        self.persian = persian
        self.manager = DependencyManager(root)
        self._prometheus_bundle = _load_prometheus_bundle()
        self.registry = self._prometheus_bundle.registry_cls()
        self.outcomes = self._prometheus_bundle.counter(
            "ci_ready_attempts_total",
            "Total CI readiness checks",
            ["outcome"],
            registry=self.registry,
        )
        self.latency = self._prometheus_bundle.gauge(
            "ci_ready_manifest_age_seconds",
            "Age delta between manifests and constraints",
            registry=self.registry,
        )

    def run(self) -> None:
        self.manager.log(
            "ci_ready_start",
            requirements=list(self.requirements),
        )
        self.manager.assert_agents_present()
        self._ensure_marker_present()
        self._ensure_constraints_fresh()
        missing = tuple(sorted(self._missing_modules(), key=self.manager.normalize_name))
        if missing:
            self.outcomes.labels(outcome="failure").inc()
            self._fail_modules(missing)
        self.outcomes.labels(outcome="success").inc()
        self._write_metrics()
        self.manager.log("ci_ready_success", missing=0)

    def _ensure_marker_present(self) -> None:
        marker = self.root / "reports" / "ci-install.json"
        if not marker.exists():
            self.manager.log("ci_ready_marker_missing", marker=str(marker))
            self._emit_failure(PERSIAN_INSTALL_ORDER)
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.manager.log("ci_ready_marker_corrupt", marker=str(marker))
            self._emit_failure(PERSIAN_INSTALL_ORDER)
        if payload.get("status") != "success":
            self.manager.log("ci_ready_marker_status", payload=payload)
            self._emit_failure(PERSIAN_INSTALL_ORDER)
        constraint_name = payload.get("constraints", "constraints-dev.txt")
        manifest_name = payload.get("manifest", "requirements-dev.in")
        constraint_path = self.root / constraint_name
        manifest_path = self.root / manifest_name
        if not constraint_path.exists() or not manifest_path.exists():
            self.manager.log(
                "ci_ready_marker_paths_missing",
                constraint=str(constraint_path),
                manifest=str(manifest_path),
            )
            self._emit_failure(PERSIAN_LOCK_MISSING)
        marker_age = marker.stat().st_mtime - max(
            manifest_path.stat().st_mtime,
            constraint_path.stat().st_mtime,
        )
        self.latency.set(marker_age)
        if marker_age < 0:
            self.manager.log(
                "ci_ready_marker_outdated",
                marker_mtime=marker.stat().st_mtime,
                manifest_mtime=manifest_path.stat().st_mtime,
                constraint_mtime=constraint_path.stat().st_mtime,
            )
            self._emit_failure(PERSIAN_INSTALL_ORDER)

    def _ensure_constraints_fresh(self) -> None:
        try:
            self.manager.ensure_constraints_fresh()
        except SystemExit as exc:
            message = str(exc)
            if message == PERSIAN_AGENTS_MISSING:
                raise
            self.manager.log("ci_ready_constraints_stale")
            self._emit_failure(PERSIAN_LOCK_MISSING)

    def _missing_modules(self) -> Iterable[str]:
        for module_name in self.requirements:
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError:
                yield module_name

    def _fail_modules(self, missing: Sequence[str]) -> None:
        context = {
            "missing": list(missing),
        }
        self.manager.log("ci_ready_missing_modules", **context)
        message = PERSIAN_PYTEST_MISSING
        if not self.persian:
            english = ", ".join(missing)
            message = (
                f"Testing prerequisites missing (import errors): {english}. "
                "Install step must precede pytest."
            )
        print(message, file=sys.stderr)
        sys.exit(2)

    def _emit_failure(self, message: str) -> None:
        self.outcomes.labels(outcome="failure").inc()
        print(message, file=sys.stderr)
        sys.exit(2)

    def _write_metrics(self) -> None:
        self.manager.log("ci_ready_write_metrics", path=str(self.metrics_path))
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.metrics_path.with_suffix(self.metrics_path.suffix + ".part")
        self._prometheus_bundle.writer(str(temp), self.registry)
        _atomic_write(self.metrics_path, temp.read_bytes())
        temp.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ensure CI prerequisites are satisfied")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--require",
        dest="requirements",
        action="append",
        default=[],
        help="Modules that must be importable",
    )
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--persian", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    guard = CiReadyGuard(
        root,
        args.requirements,
        metrics_path=args.metrics,
        persian=args.persian,
    )
    guard.run()


if __name__ == "__main__":  # pragma: no cover
    main()
