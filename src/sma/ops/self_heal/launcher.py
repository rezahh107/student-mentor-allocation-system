"""Windows self-healing launcher for the Student Mentor Allocation service."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, MutableMapping

import httpx
from prometheus_client import CollectorRegistry, Counter

from sma.core.clock import Clock, try_zoneinfo
from sma.ops.self_heal.config import SelfHealConfig

_PERSIAN_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")}
_PERSIAN_VARIANTS = {ord("ي"): "ی", ord("ك"): "ک"}
_ZERO_WIDTH = "\u200c\u200d\ufeff"

RUNBOOK_SECTION_PATTERN = re.compile(r"^###\s+(?P<section>.+?)\s*$", re.MULTILINE)
POWERSHELL_BLOCK_PATTERN = re.compile(r"```powershell\n(?P<body>.+?)\n```", re.DOTALL)


@dataclass(slots=True)
class StructuredLogEntry:
    """Structured JSON log entry persisted for the self-heal run."""

    ts: str
    level: str
    event: str
    message: str
    correlation_id: str
    context: dict[str, str]


@dataclass(slots=True)
class ErrorRecord:
    """Structured information about an encountered error."""

    step: str
    message: str
    cause: str
    fix: str
    first_seen: datetime
    occurrences: int = 1

    def to_persian_digest(self, index: int) -> str:
        template = (
            "{idx}. گام {step}: پیام='{msg}'، علت='{cause}'، راه‌حل='{fix}'، دفعات={count}"
        )
        return _normalise_persian_text(
            template.format(
                idx=index,
                step=self.step,
                msg=self.message,
                cause=self.cause,
                fix=self.fix,
                count=self.occurrences,
            )
        )


class ErrorRegistry:
    """Collects unique errors preserving order of first appearance."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._records: "OrderedDict[str, ErrorRecord]" = OrderedDict()
        self._fix_counts: "OrderedDict[str, int]" = OrderedDict()
        self._listener: Callable[[ErrorRecord], None] | None = None

    def attach_listener(self, listener: Callable[[ErrorRecord], None]) -> None:
        self._listener = listener

    def record(self, *, step: str, message: str, cause: str, fix: str) -> None:
        key = "|".join([step, message, cause, fix])
        if key not in self._records:
            record = ErrorRecord(
                step=step,
                message=message,
                cause=cause,
                fix=fix,
                first_seen=self._clock.now(),
            )
            self._records[key] = record
        else:
            record = self._records[key]
            record.occurrences += 1
        if fix not in self._fix_counts:
            self._fix_counts[fix] = 1
        else:
            self._fix_counts[fix] += 1
        if self._listener is not None:
            self._listener(record)

    def as_list(self) -> list[ErrorRecord]:
        return list(self._records.values())

    def fix_counts(self) -> "OrderedDict[str, int]":
        return OrderedDict(self._fix_counts)


@dataclass(slots=True)
class RunbookCommand:
    """Command extracted from the Windows runbook."""

    section: str
    command: str


class RunbookPlan:
    """Representation of runbook sections and PowerShell commands."""

    def __init__(self, *, raw_text: str) -> None:
        self._raw_text = raw_text
        self.commands: list[RunbookCommand] = []
        self.sections: list[str] = []
        self._parse()

    def _parse(self) -> None:
        sections = list(RUNBOOK_SECTION_PATTERN.finditer(self._raw_text))
        for match in sections:
            self.sections.append(match.group("section"))
        for block in POWERSHELL_BLOCK_PATTERN.finditer(self._raw_text):
            section = self._find_section_for_offset(block.start())
            body = block.group("body").strip().splitlines()
            for line in body:
                if line.strip() and not line.strip().startswith("#"):
                    self.commands.append(RunbookCommand(section=section, command=line.strip()))

    def _find_section_for_offset(self, offset: int) -> str:
        candidates = [
            (match.start(), match.group("section")) for match in RUNBOOK_SECTION_PATTERN.finditer(self._raw_text)
        ]
        result = ""
        for pos, section in candidates:
            if pos < offset:
                result = section
            else:
                break
        return result or "پیش‌نیاز"


@dataclass(slots=True)
class ServiceProbeResult:
    name: str
    healthy: bool
    details: str


@dataclass(slots=True)
class SelfHealResult:
    success: bool
    port: int
    errors: list[ErrorRecord] = field(default_factory=list)
    probes: list[ServiceProbeResult] = field(default_factory=list)
    fix_counts: "OrderedDict[str, int]" = field(default_factory=OrderedDict)

    def persian_digest(self) -> str:
        lines: list[str] = ["فهرست خطاهای یکتا:"]
        if not self.errors:
            lines.append("هیچ خطایی ثبت نشد؛ اجرا موفق بود.")
        else:
            for idx, record in enumerate(self.errors, start=1):
                lines.append(record.to_persian_digest(idx))
        lines.append("خلاصهٔ اقدامات اصلاحی:")
        if not self.fix_counts:
            lines.append("اقدام اصلاحی نیاز نشد.")
        else:
            for idx, (fix, count) in enumerate(self.fix_counts.items(), start=1):
                lines.append(
                    _normalise_persian_text(
                        f"{idx}. راه‌حل='{fix}'، دفعات={count}"
                    )
                )
        return "\n".join(lines)


class MissingAgentsFileError(RuntimeError):
    """Raised when AGENTS.md is absent at the repository root."""


class PowerShellCommandRunner:
    """Executes PowerShell commands while capturing structured errors."""

    def __init__(self, *, error_registry: ErrorRegistry, log: Callable[[str, str, str], None]) -> None:
        self._errors = error_registry
        self._log = log

    def run(self, command: str, *, section: str, env: MutableMapping[str, str]) -> bool:
        quoted = command if command.startswith("pwsh") else f"pwsh -NoLogo -Command {shlex.quote(command)}"
        self._log("info", "runbook-command", "اجرای دستور پاورشل", section=section, command=command)
        try:
            completed = subprocess.run(  # noqa: S603, S607
                quoted,
                shell=True,
                check=False,
                env=dict(os.environ, **env),
                capture_output=True,
                text=True,
            )
        except OSError as exc:  # pragma: no cover - subprocess creation failure
            self._errors.record(
                step=section,
                message=f"اجرای PowerShell شکست خورد: {exc.strerror}",
                cause="سیستم اجرای PowerShell در دسترس نیست.",
                fix="PowerShell 7 را نصب و PATH را بررسی کنید.",
            )
            return False
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            self._errors.record(
                step=section,
                message=f"PowerShell: «{stderr or 'خطای نامشخص'}»",
                cause="دستور runbook با خطا مواجه شد.",
                fix="خروجی را بررسی و دستور را به صورت دستی اجرا کنید.",
            )
            return False
        return True


class SelfHealLauncher:
    """Coordinates the end-to-end Windows self-healing flow."""

    def __init__(
        self,
        *,
        config: SelfHealConfig,
        clock: Clock,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._errors = ErrorRegistry(clock=clock)
        self._log_entries: list[StructuredLogEntry] = []
        self._process: subprocess.Popen[str] | None = None
        self._registry = registry or CollectorRegistry()
        self._retry_counter = Counter(
            "selfheal_retry_total",
            "Total retries executed by the self-heal orchestrator.",
            ("operation",),
            registry=self._registry,
        )
        self._exhaustion_counter = Counter(
            "selfheal_exhaustion_total",
            "Total retry exhaustion events encountered by the self-heal orchestrator.",
            ("operation",),
            registry=self._registry,
        )
        self._session_headers = {"User-Agent": "SMA-SelfHeal/1.0"}
        self._sleep: Callable[[float], None] = time_sleep_stub
        self._correlation_id: str = ""
        self._errors.attach_listener(self._log_error_record)
        self._command_runner = PowerShellCommandRunner(
            error_registry=self._errors,
            log=self._log,
        )

    def run(self) -> SelfHealResult:
        self._config.ensure_directories()
        correlation_id = self._derive_correlation_id()
        self._correlation_id = correlation_id
        self._log_entries.clear()
        self._log("info", "start", "اجرای خودترمیم آغاز شد.")
        success = False
        port = self._config.port
        probes: list[ServiceProbeResult] = []
        try:
            self._assert_agents_present()
            self._enforce_utf8()
            self._remove_uvloop_on_windows()
            timezone_resolution = try_zoneinfo(self._config.tz_name)
            if timezone_resolution.tzdata_missing:
                self._errors.record(
                    step="پیش‌نیازها",
                    message="پکیج tzdata در دسترس نیست؛ از fallback استفاده شد.",
                    cause="tzdata روی سیستم نصب نشده است.",
                    fix="با اجرای 'pip install tzdata' یا افزودن بستهٔ tzdata آن را نصب کنید.",
                )
            self._log(
                "info",
                "timezone",
                "منطقهٔ زمانی تایید شد.",
                timezone=self._config.tz_name,
                tz_fallback=str(timezone_resolution.tzdata_missing),
            )
            self._ensure_env_file()
            runbook = self._load_runbook()
            self._execute_runbook_prerequisites(runbook)
            port = self._ensure_available_port(self._config.port)
            self._log("info", "port", "پورت برای اجرا انتخاب شد.", port=str(port))
            probes = self._validate_services()
            for probe in probes:
                self._log(
                    "info" if probe.healthy else "warning",
                    "service-probe",
                    "وضعیت سرویس بررسی شد.",
                    service=probe.name,
                    healthy=str(probe.healthy),
                )
            success = self._start_application(port, runbook)
            if success:
                success = self._perform_health_checks(port)
        except MissingAgentsFileError:
            success = False
        except Exception as exc:  # pragma: no cover - safety net
            self._errors.record(
                step="اجرای خودترمیم",
                message=f"استثناء غیرمنتظره: {exc}",
                cause="اشکال ناشناخته در فرایند خودترمیم.",
                fix="جزئیات خطا و گزارش‌ها را بررسی کنید.",
            )
            success = False
        finally:
            self._teardown_process()
            errors = self._errors.as_list()
            result = SelfHealResult(
                success=success,
                port=port,
                errors=errors,
                probes=probes,
                fix_counts=self._errors.fix_counts(),
            )
            self._write_reports(result, correlation_id)
            self._log(
                "info",
                "completion",
                "اجرای خودترمیم به پایان رسید.",
                success=str(success),
                port=str(port),
            )
            self._write_log_file()
            digest = result.persian_digest()
            print(digest)
            return result

    def _derive_correlation_id(self) -> str:
        seed = f"{self._clock.now().isoformat()}|{self._config.repo_root}".encode("utf-8")
        return hashlib.blake2b(seed, digest_size=16).hexdigest()

    def _assert_agents_present(self) -> None:
        agents = self._config.repo_root / "AGENTS.md"
        agent_lower = self._config.repo_root / "agent.md"
        if not agents.exists() and not agent_lower.exists():
            message = "پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید."
            self._errors.record(
                step="پیش‌نیازها",
                message=message,
                cause="راهنمای الزامی برای عامل‌ها موجود نیست.",
                fix="فایل AGENTS.md را طبق استاندارد ایجاد کنید.",
            )
            raise MissingAgentsFileError(message)
        self._log("info", "agents", "فایل AGENTS.md تایید شد.")

    def _enforce_utf8(self) -> None:
        os.environ.setdefault("PYTHONUTF8", "1")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        self._log("info", "env", "متغیرهای UTF-8 تنظیم شد.")

    def _remove_uvloop_on_windows(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            import importlib

            importlib.import_module("uvloop")
        except ModuleNotFoundError:
            self._log("info", "uvloop", "کتابخانهٔ uvloop روی ویندوز یافت نشد.")
            return
        self._log("warning", "uvloop", "uvloop روی ویندوز یافت شد و حذف می‌شود.")
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pip", "uninstall", "-y", "uvloop"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self._errors.record(
                step="پیش‌نیازها",
                message="حذف uvloop با خطا مواجه شد.",
                cause=result.stderr.strip() or result.stdout.strip() or "unknown",
                fix="uvloop را به صورت دستی با pip uninstall حذف کنید.",
            )
        else:
            self._log("info", "uvloop", "uvloop با موفقیت حذف شد.")

    def _ensure_env_file(self) -> None:
        env_path = self._config.repo_root / ".env"
        example = self._config.repo_root / ".env.example.win"
        fallback = self._config.repo_root / ".env.example"
        if env_path.exists():
            self._log("info", "env", "فایل .env موجود بود.")
            return
        source = example if example.exists() else fallback
        if not source.exists():
            self._errors.record(
                step="ایجاد .env",
                message="نمونهٔ .env یافت نشد.",
                cause="فایل .env.example موجود نیست.",
                fix="یک فایل .env نمونه ایجاد کنید.",
            )
            return
        content = source.read_text(encoding="utf-8")
        safe_content = _normalise_persian_text(content)
        self._atomic_write(env_path, safe_content)
        self._log("info", "env", "فایل .env از نمونه ساخته شد.", source=str(source))

    def _atomic_write(self, target: Path, content: str) -> None:
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_text(content, encoding="utf-8", newline="\r\n")
        with tmp.open("rb+") as tmp_fd:
            os.fsync(tmp_fd.fileno())
        tmp.replace(target)

    def _load_runbook(self) -> RunbookPlan:
        raw = self._config.runbook_path.read_text(encoding="utf-8")
        plan = RunbookPlan(raw_text=raw)
        if not plan.sections:
            self._errors.record(
                step="خواندن راهنما",
                message="بخش‌های راهنما یافت نشد.",
                cause="قالب Markdown تغییر کرده است.",
                fix="راهنما را به‌روزرسانی و ساختار بخش‌ها را حفظ کنید.",
            )
        self._log("info", "runbook", "راهنمای ویندوز بارگذاری شد.")
        return plan

    def _execute_runbook_prerequisites(self, plan: RunbookPlan) -> None:
        env = {self._config.metrics_token_env: os.environ.get(self._config.metrics_token_env, "dev-metrics")}
        for command in plan.commands:
            if "winget" in command.command or "git clone" in command.command:
                continue
            if "Invoke-WebRequest" in command.command:
                continue
            if "uvicorn" in command.command:
                continue
            self._command_runner.run(command.command, section=command.section, env=env)

    def _ensure_available_port(self, preferred_port: int) -> int:
        if self._port_available(preferred_port):
            return preferred_port
        self._errors.record(
            step="انتخاب پورت",
            message=f"پورت {preferred_port} مشغول بود.",
            cause="سرویس دیگری در حال اجرا است.",
            fix="پورت پشتیبان استفاده شد.",
        )
        if self._port_available(self._config.fallback_port):
            return self._config.fallback_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with contextlib.closing(sock):
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def _port_available(port: int) -> bool:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
            return True

    def _validate_services(self) -> list[ServiceProbeResult]:
        probes: list[ServiceProbeResult] = []
        probes.append(self._probe_redis())
        probes.append(self._probe_postgres())
        return probes

    def _probe_redis(self) -> ServiceProbeResult:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - missing dependency path
            self._errors.record(
                step="Redis",
                message="کتابخانهٔ redis نصب نیست.",
                cause=str(exc),
                fix="pip install redis",
            )
            return ServiceProbeResult(name="redis", healthy=False, details="کتابخانهٔ redis یافت نشد")
        dsn = os.environ.get("IMPORT_TO_SABT_REDIS__DSN", "redis://localhost:6379/0")
        client = redis.Redis.from_url(dsn, socket_timeout=1.5)
        try:
            client.ping()
            return ServiceProbeResult(name="redis", healthy=True, details="PING=OK")
        except Exception as exc:  # pragma: no cover - network failure
            self._errors.record(
                step="Redis",
                message=f"Redis در دسترس نیست: {exc}",
                cause="سرویس Redis اجرا نشده است.",
                fix="Redis را راه‌اندازی و DSN را بررسی کنید.",
            )
            return ServiceProbeResult(name="redis", healthy=False, details=str(exc))
        finally:
            with contextlib.suppress(Exception):
                client.close()

    def _probe_postgres(self) -> ServiceProbeResult:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - missing dependency
            self._errors.record(
                step="PostgreSQL",
                message="کتابخانهٔ psycopg نصب نیست.",
                cause=str(exc),
                fix="pip install 'psycopg[binary]'",
            )
            return ServiceProbeResult(name="postgres", healthy=False, details="کتابخانهٔ psycopg یافت نشد")
        dsn = os.environ.get(
            "IMPORT_TO_SABT_DATABASE__DSN",
            "postgresql://postgres:postgres@localhost:5432/import_to_sabt",
        )
        try:
            with psycopg.connect(dsn, connect_timeout=1, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return ServiceProbeResult(name="postgres", healthy=True, details="SELECT 1")
        except Exception as exc:  # pragma: no cover - network failure
            self._errors.record(
                step="PostgreSQL",
                message=f"PostgreSQL در دسترس نیست: {exc}",
                cause="سرویس PostgreSQL اجرا نشده یا DSN نادرست است.",
                fix="PostgreSQL را راه‌اندازی و DSN را بررسی کنید.",
            )
            return ServiceProbeResult(name="postgres", healthy=False, details=str(exc))

    def _start_application(self, port: int, plan: RunbookPlan) -> bool:
        entrypoints = [
            "sma.phase6_import_to_sabt.app.app_factory:create_application",
            "main:app",
        ]
        env = dict(os.environ)
        env.setdefault("UVICORN_CMD", "uvicorn")
        env.setdefault(self._config.metrics_token_env, env.get(self._config.metrics_token_env, "dev-metrics"))
        for entry in entrypoints:
            cmd = (
                f"{env['UVICORN_CMD']} {entry} --factory --host 127.0.0.1 "
                f"--port {port} --workers 1"
            )
            if self._spawn_process(cmd, env=env):
                self._log("info", "uvicorn", "سرور uvicorn راه‌اندازی شد.", entry=entry, port=str(port))
                return True
        self._errors.record(
            step="راه‌اندازی سرور",
            message="هیچ ورودی uvicorn موفق نبود.",
            cause="پیکربندی یا کد برنامه مشکل دارد.",
            fix="لاگ‌های uvicorn را بررسی کنید.",
        )
        return False

    def _spawn_process(self, command: str, *, env: MutableMapping[str, str]) -> bool:
        try:
            process = subprocess.Popen(  # noqa: S603
                shlex.split(command),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            self._errors.record(
                step="راه‌اندازی سرور",
                message=f"فرمان یافت نشد: {exc.filename}",
                cause="uvicorn نصب نشده است.",
                fix="pip install uvicorn",
            )
            return False
        retcode = process.poll()
        if retcode is not None and retcode != 0:
            stderr = process.stderr.read().strip() if process.stderr else ""
            self._errors.record(
                step="راه‌اندازی سرور",
                message=f"فرآیند بلافاصله خاتمه یافت: {stderr or retcode}",
                cause="uvicorn نتوانست برنامه را اجرا کند.",
                fix="ماژول ورودی را بررسی کنید.",
            )
            with contextlib.suppress(Exception):
                process.terminate()
            return False
        self._process = process
        return True

    def _perform_health_checks(self, port: int) -> bool:
        base = f"http://127.0.0.1:{port}"
        headers = dict(self._session_headers)
        token = os.environ.get(self._config.metrics_token_env, "dev-metrics")
        headers_with_token = {**headers, "Authorization": f"Bearer {token}"}
        client = httpx.Client(timeout=2.0)
        success = False
        max_attempts = self._config.max_health_attempts
        base_delay = 0.2
        max_delay = 2.0
        try:
            for attempt in range(1, max_attempts + 1):
                self._retry_counter.labels("health").inc()
                self._log("info", "health", "تلاش برای بررسی سلامت.", attempt=str(attempt))
                try:
                    self._check_endpoint(client, f"{base}/health", headers)
                    self._check_endpoint(client, f"{base}/docs", headers)
                    self._check_endpoint(
                        client,
                        f"{base}/metrics",
                        headers_with_token,
                        expect_trace=True,
                    )
                    success = True
                    break
                except Exception as exc:  # pragma: no cover - network failure
                    success = False
                    self._log(
                        "warning",
                        "health",
                        "تلاش بررسی سلامت ناکام ماند.",
                        attempt=str(attempt),
                        error=str(exc),
                    )
                    if attempt == max_attempts:
                        self._errors.record(
                            step="سلامت سرویس",
                            message=f"بررسی سلامت شکست خورد: {exc}",
                            cause="نقاط سلامت در دسترس نبودند.",
                            fix="لاگ‌ها و پیکربندی شبکه را بررسی کنید.",
                        )
                        self._exhaustion_counter.labels("health").inc()
                        break
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    jitter = self._deterministic_jitter(attempt)
                    self._sleep(delay + jitter)
        finally:
            client.close()
        return success

    def _check_endpoint(
        self,
        client: httpx.Client,
        url: str,
        headers: MutableMapping[str, str],
        *,
        expect_trace: bool = False,
    ) -> None:
        response = client.get(url, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} for {url}")
        if expect_trace:
            trace_header = response.headers.get("X-MW-Trace")
            if trace_header and "|" in trace_header:
                chain = trace_header.split("|")[-1]
                if chain != "RateLimit>Idempotency>Auth":
                    self._errors.record(
                        step="سلامت سرویس",
                        message="ترتیب میان‌افزار نامعتبر است.",
                        cause=f"زنجیرهٔ مشاهده‌شده: {chain}",
                        fix="RateLimit → Idempotency → Auth را بازچینش کنید.",
                    )
                    raise RuntimeError("middleware-order-invalid")

    def _write_reports(self, result: SelfHealResult, correlation_id: str) -> None:
        payload = {
            "success": result.success,
            "port": result.port,
            "errors": [
                {
                    "step": error.step,
                    "message": error.message,
                    "cause": error.cause,
                    "fix": error.fix,
                    "occurrences": error.occurrences,
                    "first_seen": error.first_seen.isoformat(),
                }
                for error in result.errors
            ],
            "probes": [
                {"name": probe.name, "healthy": probe.healthy, "details": probe.details}
                for probe in result.probes
            ],
            "fix_counts": [
                {"fix": fix, "occurrences": count}
                for fix, count in result.fix_counts.items()
            ],
            "correlation_id": correlation_id,
        }
        json_path = self._config.reports_dir / "selfheal-run.json"
        five_d_path = self._config.reports_dir / "5d_plus_report.txt"
        self._atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
        evidence_lines = [
            "AGENTS.md::8 Testing & CI Gates",
            "sma/ops/self_heal/launcher.py::SelfHealLauncher",
            "tests/integration/test_self_heal_launcher.py::test_self_heal_flow",
            "tests/integration/test_self_heal_launcher.py::test_missing_agents_file_records_error",
        ]
        self._atomic_write(five_d_path, "\r\n".join(evidence_lines))

    def _write_log_file(self) -> None:
        log_path = self._config.reports_dir / "selfheal-run.log"
        if not self._log_entries:
            content = ""
        else:
            content = "\r\n".join(
                json.dumps(asdict(entry), ensure_ascii=False) for entry in self._log_entries
            )
        self._atomic_write(log_path, content)

    def _teardown_process(self) -> None:
        if self._process is None:
            return
        with contextlib.suppress(Exception):
            self._process.terminate()
            self._process.wait(timeout=3)
        self._process = None

    def _deterministic_jitter(self, attempt: int) -> float:
        correlation = self._correlation_id or "sma-self-heal"
        seed = f"{correlation}|{attempt}".encode("utf-8")
        digest = hashlib.blake2b(seed, digest_size=4).digest()
        value = int.from_bytes(digest, "big") / float(2**32)
        return round(value * 0.05, 6)

    def _log(self, level: str, event: str, message: str, **context: str) -> None:
        entry = StructuredLogEntry(
            ts=self._clock.now().isoformat(),
            level=level,
            event=event,
            message=_normalise_persian_text(message),
            correlation_id=self._correlation_id,
            context={key: self._mask_context(key, value) for key, value in context.items()},
        )
        self._log_entries.append(entry)

    def _log_error_record(self, record: ErrorRecord) -> None:
        self._log(
            "error",
            "error-recorded",
            record.message,
            step=record.step,
            cause=record.cause,
            fix=record.fix,
            occurrences=str(record.occurrences),
        )

    @staticmethod
    def _mask_context(key: str, value: str | int | float | bool | None) -> str:
        sensitive_tokens = ("token", "secret", "password", "dsn", "key")
        raw = "" if value is None else str(value)
        if any(token in key.lower() for token in sensitive_tokens):
            return "***"
        return _normalise_persian_text(raw)


def time_sleep_stub(duration: float) -> None:  # pragma: no cover - simple indirection
    import time

    time.sleep(duration)


__all__ = [
    "SelfHealLauncher",
    "SelfHealResult",
    "ServiceProbeResult",
    "RunbookPlan",
    "RunbookCommand",
]


def _normalise_persian_text(value: str) -> str:
    """Apply deterministic Persian-safe normalisation to *value*."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_PERSIAN_VARIANTS)
    normalized = normalized.translate(_PERSIAN_DIGIT_MAP)
    normalized = normalized.translate(_ARABIC_DIGIT_MAP)
    for char in _ZERO_WIDTH:
        normalized = normalized.replace(char, "")
    return normalized
