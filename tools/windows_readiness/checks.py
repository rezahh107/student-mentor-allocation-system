"""Core readiness checks for the Windows setup verifier."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from packaging.version import Version, parse as parse_version

from .clock import DeterministicClock
from .config import CLIConfig
from .fs import build_csv_rows, normalize_text
from .logging import JsonLogger
from .metrics import ReadinessMetrics

REMOTE_REGEX = re.compile(r"^https://github\.com/rezahh107/student-mentor-allocation-system(?:\.git)?$")


class CheckStatus(Enum):
    PASS = auto()
    FIXED = auto()
    WARN = auto()
    FAIL = auto()
    BLOCK = auto()


@dataclass(slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str
    weight: int
    exit_code: Optional[int] = None
    evidence: Tuple[str, ...] = ()
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GitStatus:
    present: bool = False
    ahead: int = 0
    behind: int = 0
    dirty: bool = False


@dataclass(slots=True)
class PowerShellStatus:
    path: str = ""
    version: str = ""
    execution_policy: str = ""


@dataclass(slots=True)
class SmokeStatus:
    readyz: int = 0
    metrics: int = 0
    ui_head: int = 0


@dataclass(slots=True)
class SharedState:
    remote_actual: str = ""
    git: GitStatus = field(default_factory=GitStatus)
    python_found: str = ""
    python_path: str = ""
    venv_python: str = ""
    dependencies_ok: bool = False
    powershell: PowerShellStatus = field(default_factory=PowerShellStatus)
    smoke: SmokeStatus = field(default_factory=SmokeStatus)
    evidence: List[str] = field(default_factory=list)
    retries: int = 0
    timing_ms: int = 0


class CommandError(RuntimeError):
    """Raised when a subprocess invocation fails deterministically."""

    def __init__(self, command: Sequence[str], returncode: int, stdout: str, stderr: str) -> None:
        super().__init__(f"Command {command!r} failed with exit code {returncode}")
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CheckContext:
    """Mutable context shared across readiness checks."""

    def __init__(
        self,
        config: CLIConfig,
        state: SharedState,
        logger: JsonLogger,
        clock: DeterministicClock,
        metrics: ReadinessMetrics,
    ) -> None:
        self.config = config
        self.state = state
        self.logger = logger
        self.clock = clock
        self.metrics = metrics

    def run_command(
        self,
        command: Sequence[str],
        *,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        attempts: int = 1,
        capture_output: bool = True,
        check: bool = True,
        op: str = "command",
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess with deterministic retry handling."""

        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        last_error: CommandError | None = None
        for attempt in range(1, attempts + 1):
            result = subprocess.run(
                command,
                cwd=cwd or self.config.repo_root,
                env=proc_env,
                text=True,
                capture_output=capture_output,
                timeout=timeout or self.config.timeout,
            )
            if result.returncode == 0 or not check:
                return result

            last_error = CommandError(command, result.returncode, result.stdout, result.stderr)
            if attempt < attempts:
                self.metrics.record_retry(op)
                self.state.retries += 1
                self.logger.warning(
                    "retrying_operation",
                    op=op,
                    attempt=attempt,
                    rc=result.returncode,
                    stderr=normalize_text(result.stderr),
                )
        assert last_error is not None
        raise last_error

    def ensure_python(self) -> Path:
        """Return the discovered python path raising if unavailable."""

        if not self.state.python_path:
            raise RuntimeError("python executable not discovered")
        return Path(self.state.python_path)


def _score_from_status(status: CheckStatus, weight: int) -> int:
    if status in (CheckStatus.PASS, CheckStatus.FIXED):
        return weight
    if status is CheckStatus.WARN:
        return max(weight // 2, 0)
    return 0


def check_agents(ctx: CheckContext) -> CheckResult:
    target = ctx.config.repo_root / "AGENTS.md"
    if target.exists():
        ctx.state.evidence.append("AGENTS.md::Project TL;DR")
        return CheckResult(
            name="agents",
            status=CheckStatus.PASS,
            detail="AGENTS.md در ریشهٔ مخزن یافت شد.",
            weight=10,
            evidence=("AGENTS.md::Project TL;DR",),
        )
    return CheckResult(
        name="agents",
        status=CheckStatus.BLOCK,
        detail="پروندهٔ AGENTS.md در ریشهٔ مخزن یافت نشد؛ لطفاً مطابق استاندارد agents.md اضافه کنید.",
        weight=10,
        exit_code=10,
    )


def check_git(ctx: CheckContext) -> CheckResult:
    git_dir = ctx.config.repo_root / ".git"
    if not git_dir.exists():
        return CheckResult(
            name="git",
            status=CheckStatus.FAIL,
            detail="مخزن گیت یافت نشد؛ ابتدا مخزن را کلون کنید.",
            weight=12,
            exit_code=4,
        )

    try:
        ctx.run_command(["git", "rev-parse", "--is-inside-work-tree"], op="git-rev-parse")
    except CommandError as exc:
        ctx.logger.error("git_rev_parse_failed", stderr=normalize_text(exc.stderr))
        return CheckResult(
            name="git",
            status=CheckStatus.FAIL,
            detail="عدم توانایی در تشخیص مخزن گیت.",
            weight=12,
            exit_code=4,
        )

    try:
        fetch = ctx.run_command(
            ["git", "fetch", "--prune", "--tags"],
            attempts=2,
            op="git-fetch",
        )
        ctx.logger.info("git_fetch_completed", stdout=normalize_text(fetch.stdout))
    except CommandError as exc:
        ctx.logger.warning("git_fetch_failed", stderr=normalize_text(exc.stderr))

    remote_result = ctx.run_command(
        ["git", "config", "--get", "remote.origin.url"],
        op="git-remote",
    )
    remote_url = normalize_text(remote_result.stdout.strip())
    ctx.state.remote_actual = remote_url
    ctx.state.git.present = True

    if not REMOTE_REGEX.match(remote_url):
        return CheckResult(
            name="git_remote",
            status=CheckStatus.FAIL,
            detail=f"آدرس remote دارای مقدار نامعتبر است: {remote_url or 'نامشخص'}",
            weight=12,
            exit_code=6,
        )

    status_output = ctx.run_command(
        ["git", "status", "--short", "--branch"],
        op="git-status",
    ).stdout.splitlines()

    ahead = 0
    behind = 0
    for line in status_output:
        if line.startswith("##"):
            match = re.search(r"\[ahead (\d+)\]", line)
            if match:
                ahead = int(match.group(1))
            match = re.search(r"\[behind (\d+)\]", line)
            if match:
                behind = int(match.group(1))
            continue
        if line and not line.startswith("##"):
            ctx.state.git.dirty = True

    ctx.state.git.ahead = ahead
    ctx.state.git.behind = behind
    detail = f"remote تنظیم است ({remote_url}). ahead={ahead} behind={behind} dirty={ctx.state.git.dirty}"

    if ctx.state.git.dirty and ctx.config.fix:
        return CheckResult(
            name="git_dirty",
            status=CheckStatus.BLOCK,
            detail="شاخه دارای تغییرات ذخیره‌نشده است و حالت --fix فعال است.",
            weight=12,
            exit_code=5,
        )

    return CheckResult(
        name="git",
        status=CheckStatus.PASS,
        detail=detail,
        weight=12,
        evidence=("git.remote.show:origin",),
        data={
            "ahead": ahead,
            "behind": behind,
            "dirty": ctx.state.git.dirty,
        },
    )


def _parse_python_version(output: str) -> Version:
    text = normalize_text(output)
    first_line = text.splitlines()[0] if text else ""
    match = re.search(r"(\d+\.\d+\.\d+)", first_line)
    if match:
        return parse_version(match.group(1))
    return parse_version("0.0.0")


def _python_candidates(required: str) -> List[str]:
    major_minor = required.split(".")
    candidates = []
    if sys.executable:
        candidates.append(sys.executable)
    candidates.extend(["python", "python3", "py", f"python{required}", f"py -{required}"])
    if len(major_minor) == 2:
        major = major_minor[0]
        candidates.append(f"py -{major}")
    return candidates


def check_python(ctx: CheckContext) -> CheckResult:
    required = parse_version(ctx.config.python_required)
    found_path = ""
    found_version = parse_version("0.0.0")
    candidates = _python_candidates(ctx.config.python_required)

    for candidate in candidates:
        parts = candidate.split()
        try:
            result = ctx.run_command(
                parts + ["--version"],
                op="python-detect",
            )
        except CommandError:
            continue
        version = _parse_python_version(result.stdout or result.stderr)
        if version >= required:
            found_path = parts[0]
            found_version = version
            break

    if not found_path:
        return CheckResult(
            name="python",
            status=CheckStatus.FAIL,
            detail=f"نسخهٔ پایتون {ctx.config.python_required} یافت نشد.",
            weight=14,
            exit_code=2,
        )

    ctx.state.python_found = str(found_version)
    ctx.state.python_path = found_path
    ctx.state.evidence.append(f"python.version:{found_version}")
    return CheckResult(
        name="python",
        status=CheckStatus.PASS,
        detail=f"Python {found_version} در {found_path} در دسترس است.",
        weight=14,
        evidence=(f"python.version:{found_version}",),
    )


def check_venv(ctx: CheckContext) -> CheckResult:
    venv_path = ctx.config.venv_path
    python_bin = venv_path / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")

    if not venv_path.exists():
        if ctx.config.fix:
            python_exe = ctx.ensure_python()
            ctx.logger.info("creating_virtualenv", target=str(venv_path))
            try:
                ctx.run_command(
                    [str(python_exe), "-m", "venv", str(venv_path)],
                    op="python-venv",
                )
            except CommandError as exc:
                ctx.logger.error("venv_creation_failed", stderr=normalize_text(exc.stderr))
                return CheckResult(
                    name="venv",
                    status=CheckStatus.FAIL,
                    detail="ایجاد محیط مجازی با خطا مواجه شد.",
                    weight=14,
                    exit_code=3,
                )
        else:
            return CheckResult(
                name="venv",
                status=CheckStatus.WARN,
                detail=f"محیط مجازی {venv_path} پیدا نشد.",
                weight=14,
            )

    if not python_bin.exists():
        return CheckResult(
            name="venv",
            status=CheckStatus.FAIL,
            detail="اجرایی پایتون در محیط مجازی در دسترس نیست.",
            weight=14,
            exit_code=3,
        )

    ctx.state.venv_python = str(python_bin)

    pip_result = ctx.run_command(
        [str(python_bin), "-m", "pip", "--version"],
        op="pip-version",
    )
    pip_version = _parse_python_version(pip_result.stdout)
    if pip_version < parse_version("23.0.0"):
        if ctx.config.fix:
            ctx.logger.info("upgrading_pip", version=str(pip_version))
            ctx.run_command(
                [str(python_bin), "-m", "pip", "install", "--upgrade", "pip"],
                op="pip-upgrade",
            )
        else:
            return CheckResult(
                name="pip-version",
                status=CheckStatus.WARN,
                detail="نسخهٔ pip قدیمی است؛ لطفاً به 23 به بالا ارتقا دهید.",
                weight=6,
            )

    try:
        ctx.run_command(
            [str(python_bin), "-c", "import fastapi, uvicorn; import main; assert hasattr(main, 'app')"],
            op="dependency-import",
        )
    except CommandError as exc:
        ctx.logger.warning("dependency_import_failed", stderr=normalize_text(exc.stderr))
        if ctx.config.fix:
            ctx.run_command(
                [str(python_bin), "-m", "pip", "install", "-e", "."],
                op="pip-install",
            )
            ctx.run_command(
                [str(python_bin), "-c", "import fastapi, uvicorn; import main; assert hasattr(main, 'app')"],
                op="dependency-import",
            )
        else:
            return CheckResult(
                name="venv-deps",
                status=CheckStatus.FAIL,
                detail="وابستگی‌ها کامل نصب نشده‌اند.",
                weight=14,
                exit_code=3,
            )

    ctx.state.dependencies_ok = True
    return CheckResult(
        name="venv",
        status=CheckStatus.PASS,
        detail=f"محیط مجازی در {venv_path} آماده است.",
        weight=14,
        evidence=("pip.check:fastapi",),
    )


def _powershell_candidates() -> Iterable[str]:
    executables = []
    for name in ("pwsh", "powershell", "powershell.exe"):
        path = shutil.which(name)
        if path:
            executables.append(path)
    return executables


def check_powershell(ctx: CheckContext) -> CheckResult:
    candidates = list(_powershell_candidates())
    if not candidates:
        return CheckResult(
            name="powershell",
            status=CheckStatus.FAIL,
            detail="PowerShell موجود نیست؛ لطفاً نسخهٔ 7 به بالا نصب کنید.",
            weight=10,
            exit_code=8,
        )

    selected = candidates[0]
    try:
        version_result = ctx.run_command(
            [selected, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"],
            op="powershell-version",
        )
        policy_result = ctx.run_command(
            [
                selected,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-ExecutionPolicy -Scope Process),(Get-ExecutionPolicy -Scope CurrentUser) | Select-Object -First 1",
            ],
            op="powershell-policy",
        )
    except CommandError as exc:
        ctx.logger.error("powershell_probe_failed", stderr=normalize_text(exc.stderr))
        return CheckResult(
            name="powershell",
            status=CheckStatus.FAIL,
            detail="اجرای PowerShell با خطا مواجه شد.",
            weight=10,
            exit_code=8,
        )

    version = normalize_text(version_result.stdout.strip())
    policy = normalize_text(policy_result.stdout.strip() or "Unknown")
    ctx.state.powershell = PowerShellStatus(path=selected, version=version, execution_policy=policy)
    ctx.state.evidence.append(f"powershell.executionpolicy:{policy}")

    allowed = {"Bypass", "RemoteSigned", "Unrestricted"}
    status = CheckStatus.PASS if policy in allowed else CheckStatus.WARN
    detail = f"PowerShell {version} با سیاست {policy}"

    if status is CheckStatus.WARN and ctx.config.fix:
        ctx.logger.info("powershell_policy_warning", policy=policy)

    return CheckResult(
        name="powershell",
        status=status,
        detail=detail,
        weight=10,
        evidence=(f"powershell.executionpolicy:{policy}",),
    )


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = normalize_text(key)
        value = normalize_text(value.strip().strip('"').strip("'"))
        values[key] = value
    return values


REQUIRED_ENV_KEYS = (
    "IMPORT_TO_SABT_REDIS",
    "IMPORT_TO_SABT_DATABASE",
    "IMPORT_TO_SABT_AUTH",
    "DOWNLOAD_SIGNING_KEYS",
)


def check_env_file(ctx: CheckContext) -> CheckResult:
    env_path = ctx.config.env_file
    env_values = _parse_env_file(env_path)
    if not env_values:
        return CheckResult(
            name="env-file",
            status=CheckStatus.FAIL,
            detail=f"پروندهٔ env «{env_path}» یافت نشد یا خالی است.",
            weight=10,
            exit_code=3,
        )

    missing = [key for key in REQUIRED_ENV_KEYS if key not in env_values or not env_values[key]]
    if missing:
        return CheckResult(
            name="env-file",
            status=CheckStatus.WARN,
            detail=f"کلیدهای زیر در env موجود نیستند: {', '.join(missing)}",
            weight=10,
        )

    ctx.state.evidence.append(f"env.file:{env_path.name}")
    return CheckResult(
        name="env-file",
        status=CheckStatus.PASS,
        detail="پروندهٔ env همهٔ کلیدهای ضروری را دارد.",
        weight=10,
    )


def _find_conflicting_pid(port: int) -> Optional[int]:
    try:
        import psutil  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - optional dependency
        return None

    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr and conn.laddr.port == port and conn.pid:
            return conn.pid
    return None


def check_port(ctx: CheckContext) -> CheckResult:
    pid = _find_conflicting_pid(ctx.config.port)
    if pid is None:
        return CheckResult(
            name="port",
            status=CheckStatus.PASS,
            detail=f"پورت {ctx.config.port} آزاد است.",
            weight=8,
        )

    if ctx.config.fix and ctx.config.assume_yes:
        try:
            import psutil  # type: ignore

            psutil.Process(pid).terminate()
            ctx.logger.info("terminated_process", pid=pid, port=ctx.config.port)
            return CheckResult(
                name="port",
                status=CheckStatus.FIXED,
                detail=f"فرآیند {pid} متوقف شد و پورت {ctx.config.port} آزاد گردید.",
                weight=8,
            )
        except Exception as exc:  # pragma: no cover - termination failure
            ctx.logger.error("terminate_port_failed", pid=pid, error=str(exc))
            return CheckResult(
                name="port",
                status=CheckStatus.FAIL,
                detail=f"پورت {ctx.config.port} در حال استفاده است (PID={pid}).",
                weight=8,
                exit_code=7,
            )

    return CheckResult(
        name="port",
        status=CheckStatus.FAIL,
        detail=f"پورت {ctx.config.port} در حال استفاده است (PID={pid}).",
        weight=8,
        exit_code=7,
    )


class MiddlewareAwareClient:
    """Simple HTTP client that annotates requests with middleware order header."""

    def __init__(self, port: int, timeout: int) -> None:
        self._port = port
        self._timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Middleware-Chain": "RateLimit>Idempotency>Auth",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str) -> int:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
        try:
            conn.request(method, path, headers=self._headers())
            response = conn.getresponse()
            return response.status
        finally:
            conn.close()

    def head(self, path: str) -> int:
        return self._request("HEAD", path)

    def get(self, path: str) -> int:
        return self._request("GET", path)


def check_smoke(ctx: CheckContext) -> CheckResult:
    if not ctx.state.venv_python:
        return CheckResult(
            name="smoke",
            status=CheckStatus.WARN,
            detail="اجرای smoke بدون محیط مجازی ممکن نیست.",
            weight=12,
        )

    uvicorn_cmd = [
        ctx.state.venv_python,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(ctx.config.port),
        "--env-file",
        str(ctx.config.env_file),
    ]
    proc = subprocess.Popen(
        uvicorn_cmd,
        cwd=ctx.config.repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    client = MiddlewareAwareClient(ctx.config.port, ctx.config.timeout)
    status_ready = 0
    status_metrics = 0
    status_ui = 0
    try:
        for _ in range(5):
            try:
                status_ready = client.get("/readyz")
                status_metrics = client.get("/metrics")
                status_ui = client.head("/ui")
                if status_ready == 200 and status_metrics == 200:
                    break
            except Exception:
                status_ready = status_metrics = status_ui = 0
        ctx.state.smoke = SmokeStatus(readyz=status_ready, metrics=status_metrics, ui_head=status_ui)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=ctx.config.timeout)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()

    if status_ready == 200 and status_metrics == 200:
        return CheckResult(
            name="smoke",
            status=CheckStatus.PASS,
            detail="خدمات آماده‌باش با موفقیت پاسخ دادند.",
            weight=12,
        )

    return CheckResult(
        name="smoke",
        status=CheckStatus.WARN,
        detail="پاسخ smoke تست ناموفق بود.",
        weight=12,
    )


CHECKS: Tuple[Callable[[CheckContext], CheckResult], ...] = (
    check_agents,
    check_git,
    check_python,
    check_venv,
    check_powershell,
    check_env_file,
    check_port,
    check_smoke,
)


def run_checks(ctx: CheckContext) -> Tuple[List[CheckResult], int]:
    score = 0
    results: List[CheckResult] = []
    for check in CHECKS:
        result = check(ctx)
        results.append(result)
        score += _score_from_status(result.status, result.weight)
        ctx.state.timing_ms += ctx.clock.sample_duration_ms()
        if result.exit_code:
            break
    return results, min(score, 100)


def format_csv_rows(results: Sequence[CheckResult]) -> bytes:
    rows: List[List[str]] = [["name", "status", "detail"]]
    for result in results:
        rows.append(
            [
                result.name,
                result.status.name,
                result.detail,
            ]
        )
    return build_csv_rows(rows)


__all__ = [
    "CheckContext",
    "CheckResult",
    "CheckStatus",
    "SharedState",
    "SmokeStatus",
    "GitStatus",
    "PowerShellStatus",
    "run_checks",
    "format_csv_rows",
]

