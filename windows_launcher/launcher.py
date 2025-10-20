# -*- coding: utf-8 -*-
"""Windows WebView2 launcher ensuring AGENTS.md-first execution."""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol
from uuid import uuid4

from sma.core.clock import Clock, tehran_clock
from sma.infrastructure.monitoring.logging_adapter import (
    configure_json_logging,
    correlation_id_var,
)
from sma.ops.retry import RetryMetrics, build_retry_metrics, execute_with_retry
from sma.phase6_import_to_sabt.sanitization import deterministic_jitter, sanitize_text
from windows_shared.config import (
    LauncherConfig,
    MAX_PORT,
    MIN_PORT,
    lock_path,
    load_launcher_config,
    persist_launcher_config,
)

AGENTS_MISSING_MSG = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
SERVICE_UNAVAILABLE_MSG = "راه‌اندازی سرویس ممکن نشد؛ لطفاً وضعیت سرویس پس‌زمینه را بررسی کنید."
ALREADY_RUNNING_MSG = "برنامهٔ StudentMentorApp هم‌اکنون در حال اجراست."
BACKEND_OPERATION = "backend_readiness"


class LauncherError(RuntimeError):
    """Domain error surfaced to the end-user (Persian, deterministic)."""

    def __init__(self, code: str, message: str, *, context: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


class WebviewBackend(Protocol):
    def create_window(self, title: str, url: str, **kwargs) -> object:  # pragma: no cover - protocol
        ...

    def start(self, func: Callable[..., None] | None = None) -> None:  # pragma: no cover - protocol
        ...


@dataclass(slots=True)
class FakeWebviewBackend:
    """Test double used in CI when ``FAKE_WEBVIEW=1``."""

    created_windows: list[dict] = field(default_factory=list)
    started: bool = False

    def create_window(self, title: str, url: str, **kwargs) -> dict:
        window = {"title": title, "url": url, "kwargs": kwargs}
        self.created_windows.append(window)
        return window

    def start(self, func: Callable[..., None] | None = None) -> None:
        if func:
            func()
        self.started = True


WEBVIEW2_HINT = "Runtime WebView2 یافت نشد؛ با دستور winget install Microsoft.EdgeWebView2Runtime آن را نصب کنید."


def _is_webview2_missing(exc: Exception) -> bool:
    details: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        details.append(type(current).__name__)
        details.append(str(current))
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    haystack = " ".join(details)
    keywords = ("WebView2", "EdgeChromiumInitializationError", "Edge Chromium")
    return any(keyword in haystack for keyword in keywords)


class _PyWebviewBackend:
    def __init__(self) -> None:
        import webview  # type: ignore[import-not-found]

        self._webview = webview

    def create_window(self, title: str, url: str, **kwargs) -> object:
        return self._webview.create_window(title, url=url, **kwargs)

    def start(self, func: Callable[..., None] | None = None) -> None:
        try:
            self._webview.start(func, debug=False)
        except Exception as exc:  # pragma: no cover - Windows-specific runtime detection
            if _is_webview2_missing(exc):
                raise LauncherError(
                    "WEBVIEW2_MISSING",
                    WEBVIEW2_HINT,
                    context={"detail": str(exc)},
                ) from exc
            raise


def _should_use_fake_backend() -> bool:
    return os.getenv("FAKE_WEBVIEW", "").strip().lower() not in {"", "0", "false", "no"}


def _select_backend() -> WebviewBackend:
    if _should_use_fake_backend():
        return FakeWebviewBackend()
    return _PyWebviewBackend()


class _BackendUnavailable(Exception):
    """Raised when the HTTP readiness probe fails."""


def _is_port_available(host: str, port: int) -> bool:
    tester = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tester.bind((host, port))
    except OSError:
        return False
    finally:
        tester.close()
    return True


def _allocate_port(host: str, preferred: int, *, attempts: int = 8) -> tuple[int, bool]:
    candidate = max(MIN_PORT, min(preferred, MAX_PORT))
    if _is_port_available(host, candidate):
        return candidate, False
    span = MAX_PORT - MIN_PORT
    for offset in range(1, attempts + 1):
        next_candidate = candidate + offset
        if next_candidate > MAX_PORT:
            next_candidate = MIN_PORT + ((candidate + offset) % span)
        if _is_port_available(host, next_candidate):
            return next_candidate, True
    return candidate, False


def _spawn_backend_process(port: int) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["STUDENT_MENTOR_APP_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    command = [sys.executable, "-m", "windows_service.controller", "run", "--port", str(port)]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(  # noqa: S603 - controlled command
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        creationflags=creation_flags,
    )
    return process


BackendLauncher = Callable[[int], subprocess.Popen[str] | None]


def ensure_agents_manifest(start: Path | None = None, *, max_depth: int = 6) -> Path:
    focus = (start or Path.cwd()).resolve()
    for offset, candidate in enumerate([focus, *focus.parents]):
        if offset > max_depth:
            break
        manifest = candidate / "AGENTS.md"
        if manifest.is_file():
            return manifest
    raise LauncherError("AGENTS_MISSING", AGENTS_MISSING_MSG, context={"start": str(focus)})


@dataclass(slots=True)
class SingleInstanceLock:
    path: Path
    _handle: int | None = field(default=None, init=False, repr=False)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            if os.name == "nt":  # pragma: win32-cover
                import msvcrt

                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - exercised in Linux CI
                import fcntl

                fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(handle)
            raise LauncherError("ALREADY_RUNNING", ALREADY_RUNNING_MSG) from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":  # pragma: win32-cover
                import msvcrt

                msvcrt.locking(self._handle, msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - exercised in Linux CI
                import fcntl

                fcntl.lockf(self._handle, fcntl.LOCK_UN)
        finally:
            os.close(self._handle)
            self._handle = None

    def __enter__(self) -> "SingleInstanceLock":  # pragma: no cover - trivial
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
        self.release()


def _probe_backend(port: int, correlation_id: str) -> bool:
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.settimeout(1.5)
    try:
        conn.connect(("127.0.0.1", port))
        payload = (
            f"GET /readyz HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"X-Correlation-ID: {correlation_id}\r\n"
            "Connection: close\r\n\r\n"
        )
        conn.sendall(payload.encode("ascii"))
        response = conn.recv(128)
        return response.startswith(b"HTTP/1.1 20")
    except OSError:
        return False
    finally:
        conn.close()


def _sleep(seconds: float) -> None:
    time.sleep(max(0.0, seconds))


def wait_for_backend(
    port: int,
    *,
    correlation_id: str,
    probe: Callable[[int, str], bool],
    sleep: Callable[[float], None],
    metrics: RetryMetrics,
    max_attempts: int = 6,
    jitter_base: float = 1.0,
    jitter_cap: float = 4.0,
    diagnostics: Callable[[], str] | None = None,
) -> None:
    logger = logging.getLogger(__name__)
    seed = f"{port}:{correlation_id}"
    attempt_counter = {"value": 0}
    last_detail: dict[str, str] = {"detail": "", "reason": "", "last_error": ""}

    def policy(attempt: int) -> float:
        delay = deterministic_jitter(jitter_base, attempt, seed)
        return min(delay, jitter_cap)

    def operation() -> None:
        attempt_counter["value"] += 1
        try:
            ready = probe(port, correlation_id)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            last_detail["detail"] = detail
            last_detail["reason"] = "probe_exception"
            last_detail["last_error"] = detail
            logger.warning(
                "backend_probe_exception",
                extra={"attempt": attempt_counter["value"], "port": port, "detail": detail},
            )
            raise _BackendUnavailable(f"backend:{port}") from exc
        if not ready:
            last_detail["detail"] = "probe_not_ready"
            last_detail["reason"] = "probe_not_ready"
            last_detail["last_error"] = ""
            logger.info(
                "backend_probe_retry",
                extra={"attempt": attempt_counter["value"], "port": port},
            )
            raise _BackendUnavailable(f"backend:{port}")
        last_detail["detail"] = ""
        last_detail["reason"] = ""
        last_detail["last_error"] = ""

    try:
        execute_with_retry(
            operation,
            policy=policy,
            max_attempts=max_attempts,
            metrics=metrics,
            clock_tick=sleep,
            operation_name=BACKEND_OPERATION,
        )
    except _BackendUnavailable as exc:
        context: dict[str, str] = {
            "port": str(port),
            "url": f"http://127.0.0.1:{port}/readyz",
            "reason": last_detail["reason"] or "unknown",
            "attempts": str(attempt_counter["value"]),
        }
        if last_detail["last_error"]:
            context["last_error"] = last_detail["last_error"]
        if diagnostics is not None:
            stderr_tail = diagnostics() or ""
            if stderr_tail:
                context["stderr_tail"] = stderr_tail[-1024:]
        payload = json.dumps(context, ensure_ascii=False)
        logger.error("backend_probe_failed", extra={"context": payload})
        try:
            print(payload, file=sys.stderr, flush=True)
        except OSError:
            pass
        raise LauncherError(
            "BACKEND_UNAVAILABLE",
            SERVICE_UNAVAILABLE_MSG,
            context=context,
        ) from exc


def _percentile(samples: Iterable[float], percentile: float) -> float:
    values = sorted(float(sample) for sample in samples)
    if not values:
        return 0.0
    index = int(round((len(values) - 1) * percentile))
    return values[min(index, len(values) - 1)]


def _current_memory_mb() -> float:
    try:
        import psutil  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - psutil shipped via requirements
        return 0.0
    proc = psutil.Process(os.getpid())
    return proc.memory_info().rss / (1024 * 1024)


@dataclass(slots=True)
class Launcher:
    clock: Clock = field(default_factory=tehran_clock)
    webview_backend: WebviewBackend | None = None
    probe: Callable[[int, str], bool] = field(default=_probe_backend)
    sleep: Callable[[float], None] = field(default=_sleep)
    retry_metrics: RetryMetrics | None = None
    backend_launcher: BackendLauncher | None = None
    warm_budget_seconds: float = 3.0
    cold_budget_seconds: float = 8.0
    memory_budget_mb: float = 200.0
    _startup_samples: list[float] = field(default_factory=list, init=False)
    _backend_process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _backend_last_stderr: str | None = field(default=None, init=False, repr=False)
    _teardown_registered: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.webview_backend = self.webview_backend or _select_backend()
        if self.retry_metrics is None:
            self.retry_metrics = build_retry_metrics("launcher")
        if self.backend_launcher is None:
            self.backend_launcher = _spawn_backend_process

    def _record_startup_duration(self, started_at: float, completed_at: float) -> None:
        self._startup_samples.append(max(0.0, completed_at - started_at))

    def enforce_performance_budgets(self) -> None:
        if not self._startup_samples:
            return
        cold = self._startup_samples[0]
        if cold > self.cold_budget_seconds:
            raise LauncherError(
                "COLD_START_SLOW",
                "زمان راه‌اندازی اولیه بیش از حد مجاز است.",
                context={"p95_seconds": f"{cold:.3f}"},
            )
        if len(self._startup_samples) > 1:
            warm_p95 = _percentile(self._startup_samples[1:], 0.95)
            if warm_p95 > self.warm_budget_seconds:
                raise LauncherError(
                    "WARM_START_SLOW",
                    "زمان راه‌اندازی مجدد بیش از حد مجاز است.",
                    context={"p95_seconds": f"{warm_p95:.3f}"},
                )

    def enforce_memory_budget(self) -> None:
        usage = _current_memory_mb()
        if usage > self.memory_budget_mb:
            raise LauncherError(
                "MEMORY_BUDGET_EXCEEDED",
                "مصرف حافظهٔ لانچر بیش از حد مجاز است.",
                context={"usage_mb": f"{usage:.1f}"},
            )

    def _ensure_port_availability(self, config: LauncherConfig) -> LauncherConfig:
        host = sanitize_text(config.host) or "127.0.0.1"
        requested = int(config.port)
        resolved, reassigned = _allocate_port(host, requested)
        if not _is_port_available(host, resolved):
            logging.getLogger(__name__).error(
                "backend_port_unavailable",
                extra={"host": host, "requested_port": requested},
            )
            return config
        if reassigned and resolved != requested:
            logging.getLogger(__name__).warning(
                "backend_port_conflict",
                extra={"host": host, "requested_port": requested, "fallback_port": resolved},
            )
            updated = LauncherConfig(
                port=resolved,
                host=host,
                ui_path=config.ui_path,
                version=config.version,
            )
            persist_launcher_config(updated, clock=self.clock)
            return updated
        return config

    def _ensure_backend_started(self, config: LauncherConfig, correlation_id: str) -> None:
        logger = logging.getLogger(__name__)
        try:
            if self.probe(config.port, correlation_id):
                logger.info("backend_detected_ready", extra={"port": config.port})
                return
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "backend_probe_precheck_failed",
                extra={"port": config.port, "detail": f"{type(exc).__name__}: {exc}"},
            )
        if self.backend_launcher is None:
            logger.warning("backend_launcher_missing", extra={"port": config.port})
            return
        if self._backend_process is not None:
            pid = getattr(self._backend_process, "pid", None)
            returncode = self._backend_process.poll()
            if returncode is None:
                logger.debug("backend_process_alive", extra={"port": config.port, "pid": pid})
                return
            stderr_snapshot = self._collect_backend_stderr(timeout=0.0)
            logger.warning(
                "backend_process_exited",
                extra={
                    "port": config.port,
                    "pid": pid,
                    "returncode": returncode,
                    "stderr_detail": stderr_snapshot[-512:] if stderr_snapshot else "",
                },
            )
            self._backend_process = None
        try:
            process = self.backend_launcher(config.port)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "backend_spawn_failed",
                extra={"port": config.port, "detail": f"{type(exc).__name__}: {exc}"},
            )
            return
        self._backend_process = process
        self._backend_last_stderr = None
        if process is not None:
            if not self._teardown_registered:
                atexit.register(self._terminate_backend_process)
                self._teardown_registered = True
            logger.info(
                "backend_process_spawned",
                extra={"port": config.port, "pid": getattr(process, "pid", None)},
            )

    def _collect_backend_stderr(self, *, timeout: float) -> str:
        if self._backend_process is None:
            return self._backend_last_stderr or ""
        if self._backend_last_stderr is not None:
            return self._backend_last_stderr
        if self._backend_process.stderr is None:
            return ""
        try:
            _, stderr = self._backend_process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""
        self._backend_last_stderr = (stderr or "").strip()
        return self._backend_last_stderr

    def _terminate_backend_process(self) -> None:
        process = self._backend_process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            self._collect_backend_stderr(timeout=0.2)
        except Exception:  # pragma: no cover - defensive cleanup
            pass
        finally:
            self._backend_process = None

    def _backend_stderr_snapshot(self) -> str:
        return self._collect_backend_stderr(timeout=0.0)

    def _startup_url(self, config: LauncherConfig) -> str:
        ui_path = sanitize_text(config.ui_path) or "/ui"
        return f"http://{config.host}:{config.port}{ui_path}"

    def _start_gui(self, config: LauncherConfig) -> None:
        title = "سامانه تخصیص دانش‌آموز-مربی"
        url = self._startup_url(config)
        logging.getLogger(__name__).info(
            "webview_create",
            extra={"url": url, "host": config.host, "port": config.port},
        )
        assert self.webview_backend is not None
        self.webview_backend.create_window(
            title,
            url,
            width=1280,
            height=720,
            resizable=True,
            text_select=True,
        )
        self.webview_backend.start(None)

    def run(self) -> int:
        configure_json_logging(clock=self.clock)
        corr_id = str(uuid4())
        token = correlation_id_var.set(corr_id)
        started_at = self.clock.now().timestamp()
        try:
            ensure_agents_manifest(Path(__file__).resolve().parent)
            config = load_launcher_config(clock=self.clock)
            with SingleInstanceLock(lock_path()):
                config = self._ensure_port_availability(config)
                print(f"[StudentMentorApp] backend port: {config.port}", flush=True)
                self._ensure_backend_started(config, corr_id)
                assert self.retry_metrics is not None
                metrics = self.retry_metrics
                wait_for_backend(
                    config.port,
                    correlation_id=corr_id,
                    probe=self.probe,
                    sleep=self.sleep,
                    metrics=metrics,
                    diagnostics=self._backend_stderr_snapshot,
                )
                self._record_startup_duration(started_at, self.clock.now().timestamp())
                self.enforce_memory_budget()
                self._start_gui(config)
            self.enforce_performance_budgets()
            return 0
        except LauncherError as exc:
            logging.getLogger(__name__).error(
                "launcher_error",
                extra={
                    "code": exc.code,
                    "detail": exc.message,
                    "context": json.dumps(exc.context, ensure_ascii=False),
                },
            )
            self._display_error(exc)
            return 1
        except Exception as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).exception("launcher_crash", exc_info=exc)
            self._display_error(LauncherError("UNEXPECTED", "خطای پیش‌بینی‌نشده رخ داد."))
            return 1
        finally:
            correlation_id_var.reset(token)

    def _display_error(self, error: LauncherError) -> None:
        message = error.message
        if error.context:
            details = json.dumps(error.context, ensure_ascii=False)
            message = f"{message}\n{details}"
        if _should_use_fake_backend():
            logging.getLogger(__name__).warning("gui_error", extra={"detail": message})
            return
        try:
            import ctypes  # pragma: win32-cover

            ctypes.windll.user32.MessageBoxW(0, message, "StudentMentorApp", 0x00000010)
        except Exception:  # pragma: no cover - fallback
            sys.stderr.write(f"{message}{os.linesep}")


def main() -> int:  # pragma: no cover - CLI helper
    return Launcher().run()


if __name__ == "__main__":  # pragma: no cover - script execution guard
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
