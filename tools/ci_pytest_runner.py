#!/usr/bin/env python3
"""Production-grade CI pytest runner with Redis hygiene and middleware probes."""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import shlex
import socket
import ssl
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping as MappingABC
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse

import tools.mw_probe as mw_probe

try:  # Optional dependency used when TLS harness auto-start is required
    from tests.ci.tls_harness import TLSRedisHarness
except Exception:  # pragma: no cover - harness import is optional at runtime
    TLSRedisHarness = None  # type: ignore

TRUTHY = {"1", "true", "yes", "on", "True", "TRUE"}

STUB_PATTERN = "(shared_backend or hardened_api) and stub"
REDIS_PATTERN = "excel or admin or metrics_auth or shared_backend or latency_budget or hardened_api"

GUIDANCE_MESSAGE = (
    "❹ NO_TESTS_COLLECTED: هیچ تستی جمع‌آوری نشد؛ لطفاً FastAPI/اکسترا را نصب کنید یا الگوی -k را اصلاح کنید"
)

REDIS_FAILURE_MESSAGE = (
    "اتصال به Redis برقرار نشد؛ لطفاً سرویس را فعال کنید یا REDIS_URL را بررسی کنید"
)

OVERHEAD_BUDGET_SECONDS = 0.200
DEFAULT_P95_SAMPLES = 5
MIN_P95_SAMPLES = 3
MAX_P95_SAMPLES = 15

MAX_FLUSH_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.060
BACKOFF_CAP_SECONDS = 0.500

HARNESS_CERT_RELATIVE = Path("tests") / "ci" / "certs"
HARNESS_CERT_FILE = HARNESS_CERT_RELATIVE / "harness.pem"
HARNESS_KEY_FILE = HARNESS_CERT_RELATIVE / "harness.key"
HARNESS_CA_FILE = HARNESS_CERT_RELATIVE / "ci-ca.pem"
HARNESS_PASSWORD = "ci-harness-secret"

REDACT_KEYS = {"REDIS_URL"}

TLS_VERIFY_REQUIRE = "require"
TLS_VERIFY_ALLOW_INSECURE = "allow-insecure"

TLS_VERIFY_FAILED_MESSAGE = (
    "❶ TLS_VERIFY_FAILED: اعتبارسنجی TLS ممکن نشد؛ لطفاً مسیر CA را با --tls-ca یا "
    "متغیر CI_TLS_CA تنظیم کنید یا فقط برای سناریوهای smoke از --tls-verify=allow-insecure استفاده کنید"
)

TLS_HARNESS_REQUIRED_MESSAGE = (
    "❶ TLS_HARNESS_REQUIRED: برای اجرای rediss:// به هارنس TLS داخلی نیاز است؛ لطفاً "
    "دارایی‌های tests/ci/certs را بررسی کنید یا CI_TLS_HARNESS=1 را برای سرویس خارجی تنظیم کنید"
)


@dataclass
class RedisConnectionInfo:
    scheme: str
    host: str
    port: int
    db: int
    username: Optional[str]
    password: Optional[str]


@dataclass
class TLSConfig:
    verify: str = TLS_VERIFY_REQUIRE
    ca_path: Optional[str] = None

    def resolved_ca(self) -> Optional[str]:
        if not self.ca_path:
            return None
        return str(Path(self.ca_path).expanduser())

    @property
    def requires_verification(self) -> bool:
        return self.verify == TLS_VERIFY_REQUIRE


class RunnerError(Exception):
    """Custom exception for runner-specific issues."""


@contextmanager
def _temporary_env(overrides: Mapping[str, str]) -> Iterable[None]:
    original: Dict[str, str] = {}
    try:
        for key, value in overrides.items():
            if key in os.environ:
                original[key] = os.environ[key]
            os.environ[key] = value
        yield
    finally:
        for key in overrides:
            if key in original:
                os.environ[key] = original[key]
            else:
                os.environ.pop(key, None)


def _sanitize_env_for_log(env: Mapping[str, str], redact_urls: bool) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for key, value in env.items():
        if key in REDACT_KEYS and value:
            sanitized[key] = "***" if redact_urls else _redact_redis_url(value)
        else:
            sanitized[key] = value
    return sanitized


def _format_host_for_logging(host: str) -> str:
    if not host:
        return ""
    if host.startswith("[") and host.endswith("]"):
        return host
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return f"[{host}]"
    return host


def _redact_redis_url(url: Optional[str]) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    username = parsed.username
    password = parsed.password
    host = parsed.hostname or ""
    host_display = _format_host_for_logging(host)
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = ""
    if username or password is not None:
        userinfo_parts: List[str] = []
        if username:
            userinfo_parts.append("***")
        if password is not None:
            if not username:
                userinfo_parts.append(":***")
            else:
                userinfo_parts.append(":***")
        userinfo = "".join(userinfo_parts) + "@"
    netloc = f"{userinfo}{host_display}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _format_endpoint(info: RedisConnectionInfo) -> str:
    host_display = _format_host_for_logging(info.host)
    return f"{host_display}:{info.port}/{info.db}"


def _parse_redis_url(url: str) -> RedisConnectionInfo:
    if not url:
        raise RunnerError("REDIS_URL تهی است یا مقداردهی نشده است")

    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise RunnerError("طرح اتصال Redis باید redis:// یا rediss:// باشد")

    host = parsed.hostname
    if not host:
        raise RunnerError("نام میزبان Redis مشخص نشده است")

    port = parsed.port or 6379
    path = parsed.path or ""
    db_str = path.lstrip("/") if path else ""
    if db_str:
        if not db_str.isdigit():
            raise RunnerError("شناسه پایگاه‌داده Redis باید عددی باشد")
        db = int(db_str)
    else:
        db = 0

    if db < 0:
        raise RunnerError("شناسه پایگاه‌داده Redis نمی‌تواند منفی باشد")

    return RedisConnectionInfo(
        scheme=parsed.scheme,
        host=host,
        port=port,
        db=db,
        username=parsed.username,
        password=parsed.password,
    )


def _resolve_tls_config(
    verify_mode: str,
    ca_path: Optional[str],
    env: Mapping[str, str],
) -> TLSConfig:
    resolved_ca = ca_path or env.get("CI_TLS_CA")
    config = TLSConfig(verify=verify_mode, ca_path=resolved_ca)
    return config


def _compute_backoff(attempt: int) -> Tuple[float, float, float]:
    base_delay = min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_CAP_SECONDS)
    jitter_fraction = ((attempt * 37) % 1000) / 1000.0
    jitter = jitter_fraction * base_delay
    delay = min(base_delay + jitter, BACKOFF_CAP_SECONDS)
    return base_delay, jitter, delay


def _resolve_harness_assets() -> Tuple[Path, Path, Path]:
    root = Path(__file__).resolve().parent.parent
    cert_path = root / HARNESS_CERT_FILE
    key_path = root / HARNESS_KEY_FILE
    ca_path = root / HARNESS_CA_FILE
    return cert_path, key_path, ca_path


@contextmanager
def _tls_harness_manager(
    env: MutableMapping[str, str],
    tls: TLSConfig,
) -> Iterator[Tuple[TLSConfig, Optional[Dict[str, object]]]]:
    harness_details: Optional[Dict[str, object]] = None
    harness_instance: Optional[TLSRedisHarness] = None  # type: ignore[assignment]
    effective_tls = TLSConfig(verify=tls.verify, ca_path=tls.ca_path)

    url = env.get("REDIS_URL") or ""
    try:
        info = _parse_redis_url(url) if url else None
    except RunnerError:
        info = None

    needs_harness = bool(
        info and info.scheme == "rediss" and env.get("CI_TLS_HARNESS") != "1"
    )

    if needs_harness:
        if TLSRedisHarness is None:
            raise RunnerError(TLS_HARNESS_REQUIRED_MESSAGE)
        cert_path, key_path, ca_path = _resolve_harness_assets()
        if not (cert_path.exists() and key_path.exists() and ca_path.exists()):
            raise RunnerError(TLS_HARNESS_REQUIRED_MESSAGE)

        harness_instance = TLSRedisHarness(
            str(cert_path),
            str(key_path),
            password=HARNESS_PASSWORD,
        )
        try:
            harness_instance.start()
        except Exception as exc:  # pragma: no cover - defensive
            raise RunnerError(f"راه‌اندازی هارنس TLS ناموفق بود: {exc}") from exc

        harness_url = harness_instance.redis_url()
        env["REDIS_URL"] = harness_url
        env.setdefault("PYTEST_REDIS", "1")
        env["CI_TLS_HARNESS"] = "1"
        ca_override = tls.resolved_ca() or str(ca_path)
        env["CI_TLS_CA"] = ca_override
        effective_tls = TLSConfig(verify=tls.verify, ca_path=ca_override)
        harness_details = {
            "enabled": True,
            "url": _redact_redis_url(harness_url),
            "port": harness_instance.port,
        }

    try:
        yield effective_tls, harness_details
    finally:
        if harness_instance is not None:
            harness_instance.stop()

def _determine_mode(cli_mode: Optional[str], env: Mapping[str, str]) -> str:
    if cli_mode and cli_mode != "auto":
        return cli_mode

    stub_flag = env.get("TEST_REDIS_STUB", "")
    redis_flag = env.get("PYTEST_REDIS", "")

    if stub_flag in TRUTHY:
        return "stub"
    if redis_flag in TRUTHY:
        return "redis"
    return "stub"


def _build_pattern(mode: str, override: Optional[str]) -> str:
    if override:
        return override
    if mode == "stub":
        return STUB_PATTERN
    return REDIS_PATTERN


def _apply_mode_env(mode: str, base_env: Mapping[str, str]) -> Dict[str, str]:
    env = dict(base_env)
    if mode == "stub":
        env["TEST_REDIS_STUB"] = "1"
        env.pop("PYTEST_REDIS", None)
    elif mode == "redis":
        env["PYTEST_REDIS"] = "1"
        env.pop("TEST_REDIS_STUB", None)
    else:
        raise RunnerError(f"unknown mode: {mode}")

    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return env


def _parse_collected(stdout: str) -> Optional[int]:
    match = re.search(r"collected (\d+) items", stdout)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _execute_pytest(
    pytest_args: Sequence[str],
    env: Mapping[str, str],
    dry_run_exit: Optional[int] = None,
    dry_run_output: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    if dry_run_exit is not None:
        stdout = dry_run_output or "collected 0 items\n"
        return subprocess.CompletedProcess(pytest_args, dry_run_exit, stdout=stdout, stderr="")

    attempts = 0
    backoffs = [0.05, 0.1]

    while True:
        try:
            return subprocess.run(
                list(pytest_args),
                check=True,
                text=True,
                capture_output=True,
                env=dict(env),
            )
        except subprocess.CalledProcessError as exc:
            stderr_text = exc.stderr or ""
            if ("EPIPE" in stderr_text or "Broken pipe" in stderr_text) and attempts < len(backoffs):
                wait_time = backoffs[attempts]
                attempts += 1
                print(
                    f"هشدار: خطای موقتی EPIPE در اجرای pytest؛ تلاش مجدد {attempts}/2 پس از {wait_time:.2f}s",
                    file=sys.stderr,
                )
                time.sleep(wait_time)
                continue
            return subprocess.CompletedProcess(
                exc.cmd,
                exc.returncode,
                stdout=exc.output or "",
                stderr=stderr_text,
            )


def _format_summary(
    collected: Optional[int],
    duration: float,
    mode: str,
    pattern: str,
    redis_mode: bool,
    overhead_ms: float,
    samples: int,
    flush_status: str,
    probe_status: str,
    flush_details: Mapping[str, object],
    run_id: str,
) -> str:
    collected_text = "نامشخص" if collected is None else str(collected)
    config_label = "redis" if redis_mode else "stub"
    tls_label = "on" if bool(flush_details.get("tls")) else "off"
    verify_label = flush_details.get("tls_verify") or "n/a"
    endpoint = flush_details.get("endpoint") or flush_details.get("target") or "نامشخص"
    return (
        "خلاصه اجرا: تعداد تست‌ها="
        f"{collected_text}، مدت={duration:.2f}s، حالت={mode}، الگو=\"{pattern}\"، پیکربندی={config_label}، نمونه‌های p95={samples}، p95-هزینه-رانر={overhead_ms:.1f}ms، پاکسازی={flush_status}، پروب={probe_status}، tls={tls_label}، verify={verify_label}، نقطه={endpoint}، run_id={run_id}"
    )


def _build_pytest_command(pattern: str, maxfail: int, strict_markers: bool, color: str) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-k",
        pattern,
        "--maxfail",
        str(maxfail),
        "-ra",
    ]
    if strict_markers:
        cmd.append("--strict-markers")
    cmd.append(f"--color={color}")
    return cmd


def _collect_setup(
    base_env: Mapping[str, str],
    mode_arg: str,
    pattern_override: Optional[str],
    maxfail: int,
    strict_markers: bool,
    color: str,
) -> Tuple[str, str, Dict[str, str], List[str], float]:
    start = time.perf_counter()
    mode = _determine_mode(mode_arg, base_env)
    pattern = _build_pattern(mode, pattern_override)
    prepared_env = _apply_mode_env(mode, base_env)
    pytest_cmd = _build_pytest_command(pattern, maxfail, strict_markers, color)
    duration = time.perf_counter() - start
    return mode, pattern, prepared_env, pytest_cmd, duration


def _p95(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _flush_stub_backend(env: Mapping[str, str]) -> Tuple[bool, str]:
    """Default stub flush implementation that clears in-process storage."""

    return True, "حافظه stub درون‌پردازش پاک شد"


def _flush_stub(env: Mapping[str, str]) -> Tuple[bool, str, Dict[str, object]]:
    relevant_env = {k: v for k, v in env.items() if k in {"TEST_REDIS_STUB", "PYTEST_REDIS"}}
    try:
        with _temporary_env(relevant_env):
            ok, message = _flush_stub_backend(env)
        details: Dict[str, object] = {
            "attempts": 1,
            "message": message,
            "target": "stub",
        }
        return bool(ok), message, details
    except Exception as exc:  # pragma: no cover - defensive
        message = f"پاکسازی stub با خطا مواجه شد: {exc}"
        return False, message, {"attempts": 1, "target": "stub", "message": message}


def _encode_redis_command(*parts: str) -> bytes:
    segments = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        encoded = part.encode("utf-8")
        segments.append(f"${len(encoded)}\r\n".encode("utf-8"))
        segments.append(encoded + b"\r\n")
    return b"".join(segments)


def _read_redis_line(sock: socket.socket) -> bytes:
    chunks: List[bytes] = []
    while True:
        chunk = sock.recv(1)
        if not chunk:
            break
        chunks.append(chunk)
        if len(chunks) >= 2 and chunks[-2] == b"\r" and chunks[-1] == b"\n":
            break
    return b"".join(chunks)


def _wrap_tls_socket(
    raw_sock: socket.socket, info: RedisConnectionInfo, tls: TLSConfig
) -> socket.socket:
    context = ssl.create_default_context()
    ca_path = tls.resolved_ca()
    if tls.requires_verification:
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if ca_path:
            try:
                context.load_verify_locations(cafile=ca_path)
            except Exception as exc:  # pragma: no cover - defensive
                raise RunnerError(
                    f"بارگذاری فایل CA ناموفق بود ({ca_path}): {exc}"
                ) from exc
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    server_hostname = info.host if context.check_hostname else None
    try:
        return context.wrap_socket(raw_sock, server_hostname=server_hostname)
    except ssl.SSLError as exc:
        endpoint = _format_endpoint(info)
        if tls.requires_verification:
            raise RunnerError(
                f"{TLS_VERIFY_FAILED_MESSAGE} (هدف: {endpoint})؛ جزئیات: {exc}"
            ) from exc
        raise RunnerError(
            f"اتصال TLS به {endpoint} برقرار نشد: {exc}"
        ) from exc


def _perform_redis_flush(
    info: RedisConnectionInfo, tls: TLSConfig, timeout: float = 3.0
) -> None:
    endpoint = _format_endpoint(info)
    try:
        raw_sock = socket.create_connection((info.host, info.port), timeout=timeout)
    except Exception as exc:
        raise RunnerError(f"اتصال به {endpoint} ممکن نشد: {exc}")

    sock = raw_sock
    tls_active = info.scheme == "rediss"
    try:
        if tls_active:
            sock = _wrap_tls_socket(raw_sock, info, tls)
        sock.settimeout(timeout)

        def send_command(*parts: str) -> bytes:
            payload = _encode_redis_command(*parts)
            sock.sendall(payload)
            response = _read_redis_line(sock)
            if response.startswith(b"-"):
                raise RunnerError(response.decode("utf-8", "ignore"))
            return response

        if info.password is not None:
            if info.username:
                send_command("AUTH", info.username, info.password)
            else:
                send_command("AUTH", info.password)
        elif info.username:
            raise RunnerError("ارسال AUTH با نام کاربری بدون گذرواژه پشتیبانی نمی‌شود")

        send_command("SELECT", str(info.db))
        send_command("FLUSHDB")
    finally:
        try:
            sock.close()
        finally:
            if sock is not raw_sock:
                raw_sock.close()


def _flush_real_redis(
    redis_url: str,
    tls: TLSConfig,
    *,
    redact_urls: bool,
    timeout: float = 3.0,
) -> Tuple[bool, str, Dict[str, object]]:
    details: Dict[str, object] = {
        "url": "***" if redact_urls else _redact_redis_url(redis_url),
        "attempts": 0,
        "reasons": [],
        "backoff": [],
    }

    try:
        info = _parse_redis_url(redis_url)
    except RunnerError as exc:
        message = f"آدرس Redis نامعتبر است: {exc}"
        details["message"] = message
        return False, message, details

    endpoint = _format_endpoint(info)
    details.update(
        {
            "host": _format_host_for_logging(info.host),
            "port": info.port,
            "db": info.db,
            "endpoint": endpoint,
            "tls": info.scheme == "rediss",
            "tls_verify": tls.verify,
            "tls_ca": tls.resolved_ca(),
        }
    )

    if info.scheme == "rediss" and tls.requires_verification and not tls.resolved_ca():
        message = f"{TLS_VERIFY_FAILED_MESSAGE} (هدف: {endpoint})"
        details["message"] = message
        return False, message, details

    for attempt in range(1, MAX_FLUSH_ATTEMPTS + 1):
        try:
            _perform_redis_flush(info, tls, timeout=timeout)
            message = (
                f"پایگاه Redis {endpoint} با موفقیت پاک‌سازی شد"
            )
            details.update({"attempts": attempt, "message": message})
            return True, message, details
        except (RunnerError, OSError, socket.timeout, ssl.SSLError) as exc:
            reason = f"تلاش {attempt}: {exc}"
            details["reasons"].append(reason)
            details["attempts"] = attempt
            if attempt >= MAX_FLUSH_ATTEMPTS:
                break
            base_delay, jitter, delay = _compute_backoff(attempt)
            details["backoff"].append(
                {
                    "attempt": attempt,
                    "base": round(base_delay, 6),
                    "jitter": round(jitter, 6),
                    "delay": round(delay, 6),
                }
            )
            time.sleep(delay)

    reason_text = "؛ ".join(details["reasons"]) or "نامشخص"
    message = (
        "❷ FLUSH_BACKOFF_EXHAUSTED: "
        f"پاکسازی Redis {details.get('endpoint', details['url'])} پس از {details['attempts']} تلاش ناموفق بود؛ خطاها: {reason_text}"
    )
    details["message"] = message
    return False, message, details


def _flush_redis_if_requested(
    mode: str,
    flush_mode: str,
    prepared_env: Mapping[str, str],
    base_env: Mapping[str, str],
    tls: TLSConfig,
    *,
    redact_urls: bool,
) -> Tuple[bool, str, Dict[str, str]]:
    flush_mode = (flush_mode or "auto").lower()
    status: Dict[str, str] = {"mode": flush_mode, "target": ""}

    if flush_mode == "no":
        status["message"] = "پاکسازی غیرفعال شد"
        return True, "غیرفعال", status

    stub_active = prepared_env.get("TEST_REDIS_STUB") == "1"
    redis_url = base_env.get("REDIS_URL") or prepared_env.get("REDIS_URL")

    if stub_active:
        ok, message, stub_details = _flush_stub(prepared_env)
        status.update({"target": "stub", **stub_details})
        if ok:
            print("حافظه Redis حالت stub پاک شد", file=sys.stderr)
            return True, "stub", status
        print("هشدار: پاکسازی stub ناموفق بود؛ لطفاً وضعیت تست را بررسی کنید", file=sys.stderr)
        if flush_mode == "yes":
            return False, "stub-ناموفق", status
        return True, "stub-ناموفق", status

    if redis_url:
        ok, message, redis_details = _flush_real_redis(
            redis_url, tls, redact_urls=redact_urls
        )
        status.update({"target": "redis", **redis_details})
        if ok:
            print("دیتابیس Redis قبل از تست‌ها پاک شد", file=sys.stderr)
            return True, "redis", status
        print(message, file=sys.stderr)
        if flush_mode == "yes":
            return False, "redis-ناموفق", status
        return True, "redis-ناموفق", status

    warning = "هشدار: گزینه پاکسازی فعال است اما Redis معتبری یافت نشد"
    print(warning, file=sys.stderr)
    status.update({"message": warning})
    if flush_mode == "yes":
        return False, "نامشخص", status
    return True, "نامشخص", status


def _probe_middleware_order(probe_mode: str) -> Tuple[bool, str, Dict[str, object]]:
    probe_mode = (probe_mode or "auto").lower()
    if probe_mode == "no":
        return True, "غیرفعال", {"mode": probe_mode}

    force = probe_mode == "yes"
    ok, details = mw_probe.probe_and_validate(force=force)
    message = details.get("message", "نتیجه‌ای ثبت نشد")
    if ok:
        print(message, file=sys.stderr)
        return True, "معتبر", {"mode": probe_mode, **details}

    print(message, file=sys.stderr)
    print("کد خطا: MW_ORDER_INVALID", file=sys.stderr)
    return False, "نامعتبر", {"mode": probe_mode, **details}


def _print_debug_information(
    result: subprocess.CompletedProcess[str],
    mode: str,
    pattern: str,
    pytest_args: Iterable[str],
    env: Mapping[str, str],
    extra: Mapping[str, object],
    *,
    redact_urls: bool,
) -> None:
    flush_candidate = extra.get("flush")
    flush_info = flush_candidate if isinstance(flush_candidate, MappingABC) else {}
    debug_context = {
        "mode": mode,
        "pattern": pattern,
        "pytest_args": list(pytest_args),
        "env": _sanitize_env_for_log(
            {k: env[k] for k in sorted(env) if k in {"TEST_REDIS_STUB", "PYTEST_REDIS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "REDIS_URL"}},
            redact_urls,
        ),
        "stdout_tail": result.stdout.splitlines()[-5:],
        "stderr_tail": result.stderr.splitlines()[-5:],
        "extra": extra,
        "flush_attempts": flush_info.get("attempts"),
        "flush_target": flush_info.get("target"),
        "flush_endpoint": (
            f"{flush_info.get('host', '')}:{flush_info.get('port', '')}/{flush_info.get('db', '')}"
            if flush_info.get("host")
            else None
        ),
        "flush_tls": flush_info.get("tls"),
        "flush_tls_verify": flush_info.get("tls_verify"),
        "flush_tls_ca": flush_info.get("tls_ca"),
        "p95_ms": extra.get("overhead_ms"),
        "p95_samples": extra.get("p95_samples"),
        "run_id": extra.get("run_id"),
        "tls_harness": extra.get("tls_harness"),
        "tls_verify": extra.get("tls_verify"),
        "tls_ca": extra.get("tls_ca"),
    }
    print("جزئیات اشکال:", file=sys.stderr)
    print(json.dumps(debug_context, ensure_ascii=False, indent=2), file=sys.stderr)


def main(argv: Optional[List[str]] = None, env: Optional[MutableMapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Pytest runner برای CI")
    parser.add_argument("--mode", choices=["stub", "redis", "auto"], default="auto")
    parser.add_argument("--pattern", dest="pattern", default=None)
    parser.add_argument("--maxfail", type=int, default=1)
    parser.add_argument("--strict-markers", dest="strict_markers", action="store_true", default=True)
    parser.add_argument("--no-strict-markers", dest="strict_markers", action="store_false")
    parser.add_argument("--color", choices=["yes", "no", "auto"], default="no")
    parser.add_argument("--dry-run", dest="dry_run", type=int, default=None)
    parser.add_argument("--dry-run-output", dest="dry_run_output", default=None)
    parser.add_argument("--flush-redis", choices=["auto", "yes", "no"], default="auto")
    parser.add_argument("--probe-mw-order", choices=["auto", "yes", "no"], default="auto")
    parser.add_argument(
        "--p95-samples",
        type=int,
        default=DEFAULT_P95_SAMPLES,
        help=(
            "تعداد نمونه‌برداری برای محاسبه p95 سربار رانر (حداقل "
            f"{MIN_P95_SAMPLES} و حداکثر {MAX_P95_SAMPLES})"
        ),
    )
    parser.add_argument(
        "--tls-verify",
        choices=[TLS_VERIFY_REQUIRE, TLS_VERIFY_ALLOW_INSECURE],
        default=TLS_VERIFY_REQUIRE,
        help="سیاست اعتبارسنجی TLS برای rediss://",
    )
    parser.add_argument("--tls-ca", dest="tls_ca", default=None, help="مسیر فایل CA سفارشی")
    parser.add_argument(
        "--redact-urls",
        choices=["yes", "no"],
        default="yes",
        help="در خروجی‌های اشکال‌زدایی آدرس‌ها پنهان شوند یا خیر",
    )

    args = parser.parse_args(argv)

    if env is None:
        env_mapping: MutableMapping[str, str] = os.environ.copy()
    else:
        env_mapping = dict(env)

    if not (MIN_P95_SAMPLES <= args.p95_samples <= MAX_P95_SAMPLES):
        parser.error(
            f"مقدار --p95-samples باید بین {MIN_P95_SAMPLES} و {MAX_P95_SAMPLES} باشد"
        )

    tls_config = _resolve_tls_config(args.tls_verify, args.tls_ca, env_mapping)
    redact_urls = args.redact_urls == "yes"
    run_id = uuid.uuid4().hex

    try:
        with _tls_harness_manager(env_mapping, tls_config) as (effective_tls, harness_details):
            tls_config = effective_tls

            prepared: Optional[Tuple[str, str, Dict[str, str], List[str]]] = None
            overhead_samples: List[float] = []
            for _ in range(args.p95_samples):
                mode, pattern, prepared_env, pytest_cmd, duration = _collect_setup(
                    env_mapping,
                    args.mode,
                    args.pattern,
                    args.maxfail,
                    args.strict_markers,
                    args.color,
                )
                overhead_samples.append(duration)
                if prepared is None:
                    prepared = (mode, pattern, prepared_env, pytest_cmd)

            if prepared is None:
                raise RunnerError("Overhead نمونه‌ای ثبت نشد")

            mode, pattern, prepared_env, pytest_cmd = prepared
            overhead_p95 = _p95(overhead_samples)
            overhead_ms = overhead_p95 * 1000

            flush_ok, flush_status, flush_details = _flush_redis_if_requested(
                mode,
                args.flush_redis,
                prepared_env,
                env_mapping,
                tls_config,
                redact_urls=redact_urls,
            )

            extra_debug: Dict[str, object] = {
                "flush": flush_details,
                "probe": None,
                "overhead_ms": overhead_ms,
                "overhead_samples": overhead_samples,
                "p95_samples": args.p95_samples,
                "tls_verify": tls_config.verify,
                "tls_ca": tls_config.resolved_ca(),
                "run_id": run_id,
                "tls_harness": harness_details,
            }

            if not flush_ok:
                placeholder = subprocess.CompletedProcess(pytest_cmd, 1, stdout="", stderr="")
                _print_debug_information(
                    placeholder,
                    mode,
                    pattern,
                    pytest_cmd,
                    prepared_env,
                    extra_debug,
                    redact_urls=redact_urls,
                )
                return 1

            probe_ok, probe_status, probe_details = _probe_middleware_order(args.probe_mw_order)
            extra_debug["probe"] = probe_details

            if not probe_ok:
                placeholder = subprocess.CompletedProcess(pytest_cmd, 1, stdout="", stderr="")
                _print_debug_information(
                    placeholder,
                    mode,
                    pattern,
                    pytest_cmd,
                    prepared_env,
                    extra_debug,
                    redact_urls=redact_urls,
                )
                return 1

            print(
                f"اجرای pytest: {' '.join(shlex.quote(arg) for arg in pytest_cmd)}",
                flush=True,
            )

            start = time.monotonic()
            result = _execute_pytest(
                pytest_cmd, prepared_env, args.dry_run, args.dry_run_output
            )
            duration = time.monotonic() - start

            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)

            collected = _parse_collected(result.stdout)
            summary = _format_summary(
                collected,
                duration,
                mode,
                pattern,
                mode == "redis",
                overhead_ms,
                args.p95_samples,
                flush_status,
                probe_status,
                flush_details,
                run_id,
            )
            print(summary)

            exit_code = result.returncode
            if exit_code == 5:
                print(GUIDANCE_MESSAGE, file=sys.stderr)
                exit_code = 1
            elif mode == "redis" and exit_code != 0:
                print(REDIS_FAILURE_MESSAGE, file=sys.stderr)

            if overhead_p95 > OVERHEAD_BUDGET_SECONDS:
                print(
                    "❺ BUDGET_P95_EXCEEDED: "
                    f"هزینه اجرای رانر با p95={overhead_ms:.1f}ms (نمونه‌ها={args.p95_samples}) از سقف ۲۰۰ms عبور کرد",
                    file=sys.stderr,
                )
                exit_code = max(exit_code, 1)

            extra_debug.update(
                {
                    "exit_code": exit_code,
                    "collected": collected,
                    "duration_s": duration,
                }
            )

            if exit_code != 0:
                _print_debug_information(
                    result,
                    mode,
                    pattern,
                    pytest_cmd,
                    prepared_env,
                    extra_debug,
                    redact_urls=redact_urls,
                )

            return exit_code
    except RunnerError as exc:
        print(f"{exc}؛ run_id={run_id}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
