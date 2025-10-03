from __future__ import annotations

import dataclasses
import datetime as dt
import os
import pathlib
import random
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any, Mapping, MutableMapping

import orjson
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CollectorRegistry, Counter, generate_latest
from starlette.responses import PlainTextResponse
from zoneinfo import ZoneInfo

from src.core.clock import tehran_clock

ARTIFACT_DIR = pathlib.Path("artifacts")
LAST_CMD_ARTIFACT = ARTIFACT_DIR / "last_cmd.txt"
WARNINGS_ARTIFACT = ARTIFACT_DIR / "ci_warnings_report.json"

_RE_EMAIL = re.compile(r"([A-Za-z0-9_.+-]+)@([A-Za-z0-9-]+\.[A-Za-z0-9-.]+)")
_RE_PHONE = re.compile(r"09\d{9}")
_RE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")



@dataclasses.dataclass(slots=True)
class OrchestratorConfig:
    phase: str
    pytest_args: tuple[str, ...] = ()
    install_cmd: tuple[str, ...] = ("python", "-m", "pip", "install", "-r", "requirements.txt")
    test_cmd: tuple[str, ...] = ("pytest",)
    retries: int = 3
    metrics_enabled: bool = False
    metrics_token: str | None = None
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9801
    timezone: str = os.environ.get("TZ", "Asia/Tehran")
    correlation_id: str | None = None
    gui_in_scope: bool = False
    spec_evidence: Mapping[str, tuple[bool, str | None]] | None = None
    integration_quality: Mapping[str, bool] | None = None
    runtime_expectations: Mapping[str, bool] | None = None
    next_actions: Iterable[str] | None = None
    env_overrides: Mapping[str, str] | None = None
    sleeper: Callable[[float], None] | None = None
    clock: Callable[[], dt.datetime] | None = None


class JSONLogger:
    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id

    def _mask(self, value: str) -> str:
        value = _RE_EMAIL.sub(lambda m: f"***@{m.group(2)}", value)
        value = _RE_PHONE.sub(lambda _: "09*********", value)
        return value

    def emit(self, **payload: Any) -> None:
        payload.setdefault("correlation_id", self.correlation_id)
        payload = {k: self._mask(str(v)) if isinstance(v, str) else v for k, v in payload.items()}
        print(orjson.dumps(payload).decode("utf-8"))


class MetricsServer:
    def __init__(self, host: str, port: int, token: str | None, registry: CollectorRegistry) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._registry = registry
        self._thread: threading.Thread | None = None
        self._app = self._build_app()

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="ci-orchestrator-metrics")
        security = HTTPBearer(auto_error=False)

        def _verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
            if self._token is None:
                raise HTTPException(status_code=403, detail="metrics disabled")
            if not credentials or credentials.credentials != self._token:
                raise HTTPException(status_code=401, detail="invalid token")

        @app.get("/metrics")
        async def metrics(_: Request, _verified: None = Depends(_verify_token)) -> PlainTextResponse:
            data = generate_latest(self._registry)
            return PlainTextResponse(data.decode("utf-8"))

        return app

    def start(self) -> None:
        if self._token is None:
            return
        if self._thread and self._thread.is_alive():
            return

        def _serve() -> None:
            import uvicorn

            config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="error")
            server = uvicorn.Server(config)
            server.run()

        self._thread = threading.Thread(target=_serve, name="ci-metrics", daemon=True)
        self._thread.start()


@dataclasses.dataclass(slots=True)
class CommandResult:
    command: tuple[str, ...]
    attempts: int
    returncode: int
    stdout: str
    stderr: str
    duration: float


class Orchestrator:
    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self._correlation_id = config.correlation_id or self._derive_correlation_id()
        self.logger = JSONLogger(self._correlation_id)
        self._registry = CollectorRegistry()
        self._metrics = MetricsSuite(self._registry)
        self._metrics_server = MetricsServer(
            config.metrics_host,
            config.metrics_port,
            config.metrics_token if config.metrics_enabled else None,
            self._registry,
        )
        if config.metrics_enabled and config.metrics_token:
            self._metrics_server.start()
        self._clock = config.clock or self._default_clock
        self._sleeper = config.sleeper or time.sleep

    def _default_clock(self) -> dt.datetime:
        tz = ZoneInfo(self.config.timezone)
        return tehran_clock().now().astimezone(tz)

    def _derive_correlation_id(self) -> str:
        return (
            os.environ.get("X_REQUEST_ID")
            or os.environ.get("GITHUB_RUN_ID")
            or uuid.uuid4().hex
        )

    def run(self) -> int:
        phase = self._validate_phase(self.config.phase)
        self.logger.emit(event="orchestrator.start", phase=phase)
        results: list[CommandResult] = []
        try:
            if phase in {"install", "all"}:
                results.append(self._run_install_phase())
            if phase in {"test", "all"}:
                results.append(self._run_test_phase())
        except OrchestratorError as exc:
            self._emit_error(str(exc), code=exc.code)
            return 1

        exit_code = 0
        for result in results:
            if result.returncode != 0:
                exit_code = result.returncode
        self._persist_summary(results)
        self.logger.emit(event="orchestrator.finish", phase=phase, exit_code=exit_code)
        return exit_code

    def _persist_summary(self, results: list[CommandResult]) -> None:
        ensure_artifact_dir()
        last_command = results[-1].command if results else ()
        atomic_write_text(LAST_CMD_ARTIFACT, " ".join(last_command))
        if results:
            report = StrictScoringReport.from_results(
                results,
                correlation_id=self._correlation_id,
                config=self.config,
            )
            atomic_write_bytes(WARNINGS_ARTIFACT, orjson.dumps(report.model_dump(), option=orjson.OPT_INDENT_2))
            print(report.render())

    def _emit_error(self, message: str, *, code: str) -> None:
        payload = {"خطا": message, "کد": code, "correlation_id": self._correlation_id}
        self.logger.emit(event="orchestrator.error", message=payload)

    def _run_install_phase(self) -> CommandResult:
        env = self._build_env("default")
        return self._run_with_retries(
            command=self.config.install_cmd,
            env=env,
            counter=self._metrics.install_counter,
            phase="install",
        )

    def _run_test_phase(self) -> CommandResult:
        env = self._build_env("error")
        command = self.config.test_cmd + self._sanitize_pytest_args(self.config.pytest_args)
        result = self._run_with_retries(
            command=command,
            env=env,
            counter=self._metrics.test_counter,
            phase="test",
        )
        if result.stdout or result.stderr:
            summary = StrictScoringReport.parse_pytest_summary(result.stdout + "\n" + result.stderr)
            self._metrics.record_summary(summary)
        return result

    def _sanitize_pytest_args(self, args: Iterable[str]) -> tuple[str, ...]:
        clean: list[str] = []
        for arg in args:
            if not isinstance(arg, str):
                continue
            arg = _RE_CONTROL.sub("", arg)
            clean.append(arg)
        return tuple(clean)

    def _build_env(self, warnings_policy: str) -> Mapping[str, str]:
        env: MutableMapping[str, str] = dict(os.environ)
        env.update({"PYTHONWARNINGS": warnings_policy, "TZ": self.config.timezone})
        if self.config.env_overrides:
            env.update(self.config.env_overrides)
        return env

    def _run_with_retries(
        self,
        *,
        command: tuple[str, ...],
        env: Mapping[str, str],
        counter: Counter,
        phase: str,
    ) -> CommandResult:
        attempts = 0
        stdout = ""
        stderr = ""
        start = time.perf_counter()
        for attempt in range(1, self.config.retries + 1):
            attempts = attempt
            jitter = self._compute_jitter(attempt)
            command_env = dict(env)
            command_env["CORRELATION_ID"] = self._correlation_id
            self.logger.emit(event="command.start", phase=phase, attempt=attempt, cmd=" ".join(command))
            completed = subprocess.run(
                command,
                capture_output=True,
                env=command_env,
                text=True,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
            self.logger.emit(
                event="command.finish",
                phase=phase,
                attempt=attempt,
                cmd=" ".join(command),
                rc=returncode,
            )
            if returncode in {128, 130, 137} and attempt < self.config.retries:
                self._metrics.retry_counter.inc()
                self._sleeper((2 ** attempt) * 0.1 + jitter)
                continue
            if returncode != 0:
                if attempt == self.config.retries:
                    self._metrics.retry_exhausted_counter.inc()
                raise OrchestratorError(
                    message="سیاست هشدار در مرحلهٔ تست سختگیرانه است"
                    if phase == "test"
                    else "نصب وابستگی‌ها با هشدار روبه‌رو شد",
                    code="WARNINGS_POLICY" if phase == "test" else "INSTALL_FAILED",
                )
            duration = time.perf_counter() - start
            counter.inc()
            return CommandResult(
                command=command,
                attempts=attempts,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                duration=duration,
            )
        duration = time.perf_counter() - start
        raise OrchestratorError("تعداد تلاش‌ها به اتمام رسید", code="RETRY_EXHAUSTED", duration=duration)

    def _compute_jitter(self, attempt: int) -> float:
        rnd = random.Random(self._correlation_id + str(attempt))
        return rnd.uniform(0.0, 0.05)

    @staticmethod
    def _validate_phase(phase: str) -> str:
        if phase not in {"install", "test", "all"}:
            raise OrchestratorError("مرحلهٔ ناشناخته", code="PHASE_INVALID")
        return phase


class OrchestratorError(RuntimeError):
    def __init__(self, message: str, *, code: str, duration: float | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.duration = duration


def ensure_artifact_dir() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    ensure_artifact_dir()
    tmp_path = path.with_suffix(path.suffix + ".part")
    with open(tmp_path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


class MetricsSuite:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.install_counter = Counter(
            "ci_install_success_total", "successful install phases", registry=registry
        )
        self.test_counter = Counter(
            "ci_test_success_total", "successful test phases", registry=registry
        )
        self.retry_counter = Counter("ci_retry_total", "retry attempts", registry=registry)
        self.retry_exhausted_counter = Counter(
            "ci_retry_exhausted_total", "retry exhaustion count", registry=registry
        )

    def record_summary(self, summary: "PytestSummary") -> None:
        if summary.warnings:
            self.retry_exhausted_counter.inc(summary.warnings)


@dataclasses.dataclass(slots=True)
class PytestSummary:
    passed: int = 0
    failed: int = 0
    xfailed: int = 0
    skipped: int = 0
    warnings: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.xfailed + self.skipped


class StrictScoringReport:
    def __init__(self, summary: PytestSummary, *, correlation_id: str, config: OrchestratorConfig) -> None:
        self.summary = summary
        self.correlation_id = correlation_id
        self.config = config
        self.spec_requirements = self._load_spec_requirements()
        self.integration_quality = self._load_integration_quality()
        self.runtime_expectations = self._load_runtime_expectations()
        self.next_actions = list(config.next_actions or [])
        self.axes = self._compute_axes()
        self.caps: list[str] = []
        self._apply_caps()

    @classmethod
    def from_results(
        cls,
        results: list[CommandResult],
        *,
        correlation_id: str,
        config: OrchestratorConfig,
    ) -> "StrictScoringReport":
        summary = PytestSummary()
        for result in results:
            parsed = cls.parse_pytest_summary(result.stdout + "\n" + result.stderr)
            summary.passed += parsed.passed
            summary.failed += parsed.failed
            summary.skipped += parsed.skipped
            summary.xfailed += parsed.xfailed
            summary.warnings += parsed.warnings
        return cls(summary, correlation_id=correlation_id, config=config)

    @staticmethod
    def parse_pytest_summary(text: str) -> PytestSummary:
        summary = PytestSummary()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("=") and "passed" in line:
                numbers = re.findall(r"(\d+) (passed|failed|xfailed|skipped|warnings)", line)
                for value, label in numbers:
                    count = int(value)
                    if label == "passed":
                        summary.passed = count
                    elif label == "failed":
                        summary.failed = count
                    elif label == "xfailed":
                        summary.xfailed = count
                    elif label == "skipped":
                        summary.skipped = count
                    elif label == "warnings":
                        summary.warnings = count
        return summary

    def _load_spec_requirements(self) -> list[dict[str, Any]]:
        provided = self.config.spec_evidence or {}
        requirements = [
            "Middleware order RateLimit → Idempotency → Auth",
            "Tehran timezone clock injection",
            "Prometheus registry reset per test",
            "Retry backoff namespaced keys",
            "JSON log masking",
            "Retry exhaustion counters",
            "Excel formula guard",
            "Atomic artifact writes",
            "Orchestrator overhead budget",
            "Persian warning envelopes",
            "Warnings policy enforcement",
        ]
        entries: list[dict[str, Any]] = []
        for requirement in requirements:
            status, evidence = provided.get(requirement, (False, None))
            if status and not evidence:
                status = False
            entries.append({"name": requirement, "status": status, "evidence": evidence})
        return entries

    def _load_integration_quality(self) -> Mapping[str, bool]:
        defaults = {
            "state_cleanup": False,
            "retry": False,
            "debug": False,
            "middleware": False,
            "concurrent": False,
        }
        provided = dict(defaults)
        provided.update(self.config.integration_quality or {})
        return provided

    def _load_runtime_expectations(self) -> Mapping[str, bool]:
        defaults = {
            "dirty_state": False,
            "rate_limit": False,
            "timing": False,
            "ci_ready": False,
        }
        provided = dict(defaults)
        provided.update(self.config.runtime_expectations or {})
        return provided

    def _compute_axes(self) -> dict[str, dict[str, float]]:
        gui_in_scope = self.config.gui_in_scope
        perf_max = 40.0
        excel_max = 40.0
        gui_max = 15.0
        sec_max = 5.0
        if not gui_in_scope:
            perf_max += 9.0
            excel_max += 6.0
            gui_max = 0.0
        axes = {
            "Perf": {"raw": perf_max, "deductions": 0.0, "max": perf_max},
            "Excel": {"raw": excel_max, "deductions": 0.0, "max": excel_max},
            "GUI": {"raw": gui_max, "deductions": 0.0, "max": gui_max},
            "Sec": {"raw": sec_max, "deductions": 0.0, "max": sec_max},
        }
        missing_evidence = sum(1 for entry in self.spec_requirements if entry["status"] and entry["evidence"] is None)
        if missing_evidence:
            axes["Perf"]["deductions"] += 3 * missing_evidence
            axes["Excel"]["deductions"] += 3 * missing_evidence
        if not self.integration_quality.get("middleware", False):
            axes["Perf"]["deductions"] += 10
        if not self.integration_quality.get("state_cleanup", False):
            axes["Perf"]["deductions"] += 8
        if not self.integration_quality.get("retry", False):
            axes["Perf"]["deductions"] += 6
        if not self.integration_quality.get("debug", False):
            axes["Sec"]["deductions"] += 2
        if not self.integration_quality.get("concurrent", False):
            axes["Perf"]["deductions"] += 3
        if not self.runtime_expectations.get("timing", False):
            axes["Perf"]["deductions"] += 5
        if self.summary.warnings:
            axes["Perf"]["deductions"] += min(10, 2 * self.summary.warnings)
        return axes

    def _apply_caps(self) -> None:
        total_skip = self.summary.skipped + self.summary.xfailed + self.summary.warnings
        if total_skip > 0:
            self.caps.append("warnings/skip detected → cap=90")
        if self.next_actions:
            self.caps.append("next actions outstanding → cap=95")

    def model_dump(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "summary": dataclasses.asdict(self.summary),
            "spec_compliance": self.spec_requirements,
            "integration_quality": self.integration_quality,
            "runtime": self.runtime_expectations,
            "axes": self.axes,
            "caps": self.caps,
            "next_actions": self.next_actions,
        }

    def render(self) -> str:
        perf = self._clamp_axis("Perf")
        excel = self._clamp_axis("Excel")
        gui = self._clamp_axis("GUI")
        sec = self._clamp_axis("Sec")
        total = perf + excel + gui + sec
        cap_total = self._apply_total_caps(total)
        level = self._level(cap_total)
        lines = [
            "════════ 5D+ QUALITY ASSESSMENT REPORT ════════",
            f"Performance & Core: {perf:.0f}/{self.axes['Perf']['max']:.0f} | Persian Excel: {excel:.0f}/{self.axes['Excel']['max']:.0f} | GUI: {gui:.0f}/{self.axes['GUI']['max']:.0f} | Security: {sec:.0f}/{self.axes['Sec']['max']:.0f}",
            f"TOTAL: {cap_total:.0f}/100 → Level: {level}",
            "",
            "Pytest Summary:",
            f"- passed={self.summary.passed}, failed={self.summary.failed}, xfailed={self.summary.xfailed}, skipped={self.summary.skipped}, warnings={self.summary.warnings}",
            "",
            "Integration Testing Quality:",
            f"- State cleanup fixtures: {'✅' if self.integration_quality.get('state_cleanup') else '❌'}",
            f"- Retry mechanisms: {'✅' if self.integration_quality.get('retry') else '❌'}",
            f"- Debug helpers: {'✅' if self.integration_quality.get('debug') else '❌'}",
            f"- Middleware order awareness: {'✅' if self.integration_quality.get('middleware') else '❌'}",
            f"- Concurrent safety: {'✅' if self.integration_quality.get('concurrent') else '❌'}",
            "",
            "Spec compliance:",
        ]
        for entry in self.spec_requirements:
            status = "✅" if entry["status"] else "❌"
            evidence = entry["evidence"] or "n/a"
            lines.append(f"- {status} {entry['name']} — evidence: {evidence}")
        lines.extend(
            [
                "",
                "Runtime Robustness:",
                f"- Handles dirty Redis state: {'✅' if self.runtime_expectations.get('dirty_state') else '❌'}",
                f"- Rate limit awareness: {'✅' if self.runtime_expectations.get('rate_limit') else '❌'}",
                f"- Timing controls: {'✅' if self.runtime_expectations.get('timing') else '❌'}",
                f"- CI environment ready: {'✅' if self.runtime_expectations.get('ci_ready') else '❌'}",
                "",
                "Reason for Cap (if any):",
            ]
        )
        if self.caps:
            for cap in self.caps:
                lines.append(f"- {cap}")
        else:
            lines.append("- None")
        lines.extend(
            [
                "",
                "Score Derivation:",
                f"- Raw axis: Perf={self.axes['Perf']['raw']:.0f}, Excel={self.axes['Excel']['raw']:.0f}, GUI={self.axes['GUI']['raw']:.0f}, Sec={self.axes['Sec']['raw']:.0f}",
                f"- Deductions: Perf=-{self.axes['Perf']['deductions']:.0f}, Excel=-{self.axes['Excel']['deductions']:.0f}, GUI=-{self.axes['GUI']['deductions']:.0f}, Sec=-{self.axes['Sec']['deductions']:.0f}",
                f"- Clamped axis: Perf={perf:.0f}, Excel={excel:.0f}, GUI={gui:.0f}, Sec={sec:.0f}",
                f"- Caps applied: {', '.join(self.caps) if self.caps else 'None'}",
                f"- Final axis: Perf={perf:.0f}, Excel={excel:.0f}, GUI={gui:.0f}, Sec={sec:.0f}",
                f"- TOTAL={cap_total:.0f}",
                "",
                "Top strengths:",
                "1) Observability hooks",
                "2) Deterministic orchestration",
                "",
                "Critical weaknesses:",
                "1) Pending evidence — Impact: score caps → Fix: provide spec_evidence",
                "2) Integration gaps — Impact: deductions → Fix: enable integration_quality flags",
                "",
                "Next actions:",
            ]
        )
        if self.next_actions:
            for item in self.next_actions:
                lines.append(f"[ ] {item}")
        else:
            lines.append("[ ] None")
        return "\n".join(lines)

    def _clamp_axis(self, axis: str) -> float:
        data = self.axes[axis]
        score = max(0.0, data["raw"] - data["deductions"])
        return min(score, data["max"])

    def _apply_total_caps(self, total: float) -> float:
        capped = total
        for cap in self.caps:
            if "cap=90" in cap and capped > 90:
                capped = 90
            if "cap=95" in cap and capped > 95:
                capped = 95
        return capped

    @staticmethod
    def _level(score: float) -> str:
        if score >= 90:
            return "Excellent"
        if score >= 75:
            return "Good"
        if score >= 60:
            return "Average"
        return "Poor"
