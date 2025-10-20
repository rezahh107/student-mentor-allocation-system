# -*- coding: utf-8 -*-
"""WinSW-compatible controller for the FastAPI backend service."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from prometheus_client import Counter, REGISTRY

from sma.core.clock import Clock, tehran_clock
from sma.core.retry import (
    RetryExhaustedError,
    RetryPolicy,
    build_sync_clock_sleeper,
    execute_with_retry,
)
from sma.infrastructure.monitoring.logging_adapter import (
    configure_json_logging,
    correlation_id_var,
)
from sma.phase6_import_to_sabt.sanitization import secure_digest
from windows_service.errors import DependencyNotReady, ServiceError
from windows_service.normalization import sanitize_env_text
from windows_service.readiness import probe_dependencies
from windows_shared.config import LauncherConfig, load_launcher_config

REQUIRED_ENVS: dict[str, str] = {
    "DATABASE_URL": "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است.",
    "REDIS_URL": "پیکربندی ناقص است؛ متغیر REDIS_URL خالی است.",
    "METRICS_TOKEN": "پیکربندی ناقص است؛ متغیر METRICS_TOKEN خالی است.",
}

EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def _safe_counter(name: str, documentation: str) -> Counter:
    with contextlib.suppress(ValueError):
        return Counter(name, documentation, labelnames=("outcome",))
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Counter):
        return existing
    raise


READINESS_BACKOFF_TOTAL = _safe_counter(
    "winsw_readiness_backoff_total",
    "Number of readiness backoff operations for WinSW controller.",
)


def _default_winsw_path() -> Path:
    override = os.getenv("STUDENT_MENTOR_WINSW")
    if override:
        return Path(override).expanduser()
    return Path(__file__).with_name("StudentMentorService.exe")


def _default_winsw_xml() -> Path:
    return Path(__file__).with_name("StudentMentorService.xml")


def _normalise_env(name: str, value: str | None) -> str:
    text = sanitize_env_text(value or "")
    if not text or text.lower() in {"null", "none", "undefined"}:
        raise ServiceError("CONFIG_MISSING", REQUIRED_ENVS[name], context={"variable": name})
    return text


def _validate_environment() -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, message in REQUIRED_ENVS.items():
        raw = os.getenv(key)
        try:
            validated[key] = _normalise_env(key, raw)
        except ServiceError as exc:
            raise ServiceError(exc.code, message, context={"variable": key}) from exc
    return validated


def _run_uvicorn(port: int) -> None:
    import uvicorn  # type: ignore[import-not-found]

    clock = tehran_clock()
    configure_json_logging(clock=clock)
    token = correlation_id_var.set(str(uuid4()))
    try:
        uvicorn.run(
            "sma.infrastructure.api.routes:create_app",
            factory=True,
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            log_level="debug",
        )
    finally:
        correlation_id_var.reset(token)


CommandExecutor = Callable[[Sequence[str]], subprocess.CompletedProcess[bytes]]


def _default_dependency_probe(env: dict[str, str]) -> None:
    timeout = float(os.getenv("SMASM_READINESS_TIMEOUT", "1.5"))
    probe_dependencies(env["DATABASE_URL"], env["REDIS_URL"], timeout)


def _subprocess_executor(args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, check=True, capture_output=True)


@dataclass(slots=True)
class ServiceController:
    winsw_executable: Path = field(default_factory=_default_winsw_path)
    winsw_xml: Path = field(default_factory=_default_winsw_xml)
    executor: CommandExecutor = field(default_factory=lambda: _subprocess_executor)
    uvicorn_runner: Callable[[int], None] = field(default_factory=lambda: _run_uvicorn)
    clock: Clock = field(default_factory=tehran_clock)
    port_override: int | None = None
    dependency_probe: Callable[[dict[str, str]], None] = field(
        default_factory=lambda: _default_dependency_probe
    )

    def handle(self, command: str) -> int:
        if command == "run":
            return self._run()
        if command not in {"install", "start", "stop", "uninstall"}:
            raise ServiceError("COMMAND_UNKNOWN", "دستور نامعتبر است.", context={"command": command})
        return self._invoke_winsw(command)

    def _run(self) -> int:
        config = self._load_launcher_config()
        env_values = _validate_environment()
        port = self.port_override if self.port_override is not None else config.port
        os.environ.setdefault("STUDENT_MENTOR_APP_PORT", str(port))
        logging.getLogger(__name__).info("service_run", extra={"port": port})
        self._await_dependencies(env_values, port)
        try:
            self.uvicorn_runner(port)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.getLogger(__name__).exception(
                "service_run_failed",
                extra={"detail": f"{type(exc).__name__}: {exc}"},
            )
            return EXIT_RUNTIME_ERROR
        return EXIT_SUCCESS

    def _invoke_winsw(self, command: str) -> int:
        if not self.winsw_executable.is_file():
            raise ServiceError(
                "WINSW_MISSING",
                "پروندهٔ اجرای WinSW در دسترس نیست.",
                context={"path": str(self.winsw_executable)},
            )
        if not self.winsw_xml.is_file():
            raise ServiceError(
                "XML_MISSING",
                "پیکربندی XMLِ سرویس یافت نشد.",
                context={"path": str(self.winsw_xml)},
            )
        args = [str(self.winsw_executable), command]
        logging.getLogger(__name__).info("winsw_exec", extra={"winsw_args": args})
        try:
            result = self.executor(args)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).error(
                "winsw_error",
                extra={"command": command, "returncode": exc.returncode},
            )
            return EXIT_RUNTIME_ERROR
        if result.returncode != 0:
            logging.getLogger(__name__).error(
                "winsw_nonzero",
                extra={"command": command, "returncode": result.returncode},
            )
            return EXIT_RUNTIME_ERROR
        return EXIT_SUCCESS

    def _load_launcher_config(self) -> LauncherConfig:
        return load_launcher_config(clock=self.clock)

    def _await_dependencies(self, env_values: dict[str, str], port: int) -> None:
        base_delay = float(os.getenv("SMASM_READINESS_BASE_DELAY", "0.25"))
        factor = float(os.getenv("SMASM_READINESS_FACTOR", "2.0"))
        max_delay = float(os.getenv("SMASM_READINESS_MAX_DELAY", "2.0"))
        max_attempts = int(os.getenv("SMASM_READINESS_MAX_ATTEMPTS", "5"))
        policy = RetryPolicy(
            base_delay=base_delay,
            factor=factor,
            max_delay=max_delay,
            max_attempts=max_attempts,
        )
        sleeper = build_sync_clock_sleeper(self.clock)
        seed = secure_digest(f"winsw:{port}")
        corr = correlation_id_var.get() or seed
        token = None
        if not correlation_id_var.get():
            token = correlation_id_var.set(corr)

        def _sleeper(seconds: float) -> None:
            READINESS_BACKOFF_TOTAL.labels(outcome="retry").inc()
            sleeper(seconds)

        try:
            execute_with_retry(
                lambda: self.dependency_probe(env_values),
                policy=policy,
                clock=self.clock,
                sleeper=_sleeper,
                retryable=(DependencyNotReady,),
                correlation_id=corr,
                op="winsw_readiness_probe",
            )
        except RetryExhaustedError as exc:
            READINESS_BACKOFF_TOTAL.labels(outcome="exhausted").inc()
            message = "سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند."
            context = {
                "op": "winsw_readiness_probe",
                "attempts": str(max_attempts),
                "last_error": type(exc.last_error).__name__ if exc.last_error else "unknown",
                "port": str(port),
            }
            logging.getLogger(__name__).error(
                "service_dependencies_unavailable",
                extra={"context": json.dumps(context, ensure_ascii=False)},
            )
            raise ServiceError("READINESS_FAILED", message, context=context) from exc
        else:
            READINESS_BACKOFF_TOTAL.labels(outcome="success").inc()
        finally:
            if token is not None:
                correlation_id_var.reset(token)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student Mentor backend service controller.")
    parser.add_argument(
        "command",
        choices=["install", "start", "stop", "uninstall", "run"],
        help="Operation to execute.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override backend port when using the 'run' command.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.port is not None and args.command != "run":
        raise ServiceError(
            "PORT_NOT_SUPPORTED",
            "گزینهٔ --port فقط برای دستور run مجاز است.",
            context={"command": args.command},
        )
    clock = tehran_clock()
    configure_json_logging(clock=clock)
    controller = ServiceController(
        port_override=args.port if args.command == "run" else None,
        clock=clock,
    )
    try:
        return controller.handle(args.command)
    except ServiceError as exc:
        logging.getLogger(__name__).exception(
            "service_error",
            extra={
                "code": exc.code,
                "detail": exc.message,
                "context": json.dumps(exc.context, ensure_ascii=False),
            },
        )
        raise


if __name__ == "__main__":  # pragma: no cover - CLI execution
    try:
        raise SystemExit(main())
    except ServiceError as exc:
        raise SystemExit(EXIT_CONFIG_ERROR) from exc
