# -*- coding: utf-8 -*-
"""WinSW-compatible controller for the FastAPI backend service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from src.core.clock import Clock, tehran_clock
from src.infrastructure.monitoring.logging_adapter import (
    configure_json_logging,
    correlation_id_var,
)
from src.phase6_import_to_sabt.sanitization import sanitize_text
from windows_shared.config import LauncherConfig, load_launcher_config

REQUIRED_ENVS: dict[str, str] = {
    "DATABASE_URL": "پیکربندی ناقص است؛ متغیر DATABASE_URL خالی است.",
    "REDIS_URL": "پیکربندی ناقص است؛ متغیر REDIS_URL خالی است.",
    "METRICS_TOKEN": "توکن متریک تنظیم نشده است.",
}

EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 3


class ServiceError(RuntimeError):
    """Raised when controller preconditions fail."""

    def __init__(self, code: str, message: str, *, context: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


def _default_winsw_path() -> Path:
    override = os.getenv("STUDENT_MENTOR_WINSW")
    if override:
        return Path(override).expanduser()
    return Path(__file__).with_name("StudentMentorService.exe")


def _default_winsw_xml() -> Path:
    return Path(__file__).with_name("StudentMentorService.xml")


def _normalise_env(name: str, value: str | None) -> str:
    text = sanitize_text(value or "")
    if not text:
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
    correlation_id_var.set(str(uuid4()))
    uvicorn.run(
        "src.infrastructure.api.routes:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
    )


CommandExecutor = Callable[[Sequence[str]], subprocess.CompletedProcess[bytes]]


def _subprocess_executor(args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, check=True, capture_output=True)


@dataclass(slots=True)
class ServiceController:
    winsw_executable: Path = field(default_factory=_default_winsw_path)
    winsw_xml: Path = field(default_factory=_default_winsw_xml)
    executor: CommandExecutor = field(default_factory=lambda: _subprocess_executor)
    uvicorn_runner: Callable[[int], None] = field(default_factory=lambda: _run_uvicorn)
    clock: Clock = field(default_factory=tehran_clock)

    def handle(self, command: str) -> int:
        if command == "run":
            return self._run()
        if command not in {"install", "start", "stop", "uninstall"}:
            raise ServiceError("COMMAND_UNKNOWN", "دستور نامعتبر است.", context={"command": command})
        return self._invoke_winsw(command)

    def _run(self) -> int:
        config = self._load_launcher_config()
        _validate_environment()
        try:
            self.uvicorn_runner(config.port)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.getLogger(__name__).exception("service_run_failed", exc_info=exc)
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
                "پروندهٔ پیکربندی StudentMentorService.xml یافت نشد.",
                context={"path": str(self.winsw_xml)},
            )
        args = [str(self.winsw_executable), command]
        logging.getLogger(__name__).info("winsw_exec", extra={"args": args})
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Student Mentor backend service controller.")
    parser.add_argument(
        "command",
        choices=["install", "start", "stop", "uninstall", "run"],
        help="Operation to execute.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_json_logging()
    controller = ServiceController()
    try:
        return controller.handle(args.command)
    except ServiceError as exc:
        logging.getLogger(__name__).error(
            "service_error",
            extra={
                "code": exc.code,
                "detail": exc.message,
                "context": json.dumps(exc.context, ensure_ascii=False),
            },
        )
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":  # pragma: no cover - CLI execution
    raise SystemExit(main())
