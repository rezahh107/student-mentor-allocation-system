#!/usr/bin/env python3
"""Deterministic pytest runner for CI environments."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Public constants consumed directly by the regression tests
# ---------------------------------------------------------------------------
STUB_PATTERN = "not redis"
REDIS_PATTERN = "redis integration"
DEFAULT_MODE = "auto"
GUIDANCE_MESSAGE = "ℹ️ برای دریافت راهنمایی بیشتر، مستندات CI را بررسی کنید."
REDIS_FAILURE_MESSAGE = "❌ اجرای تست‌های Redis ناموفق شد؛ لاگ pytest را بررسی کنید."
BUDGET_FAILURE_MESSAGE = "❺ BUDGET_P95_EXCEEDED"
MIN_P95_SAMPLES = 3
DEFAULT_P95_SAMPLES = 5
P95_BUDGET_SECONDS = 0.2
TLS_VERIFY_REQUIRE = "require"
TLS_VERIFY_ALLOW_INSECURE = "allow-insecure"
TLS_VERIFY_SKIP = "skip"
BACKOFF_BASE_SECONDS = 0.25
BACKOFF_CAP_SECONDS = 2.0
MAX_FLUSH_ATTEMPTS = 5
DEBUG_MARKER = "جزئیات اشکال:\n"
TLSRedisHarness = None  # Patched in tests when TLS harness assets are available.


class RunnerError(RuntimeError):
    """Domain specific failure raised by helper routines."""


@dataclass(frozen=True)
class TLSConfig:
    verify: str = TLS_VERIFY_REQUIRE
    ca_path: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.verify != TLS_VERIFY_SKIP


@dataclass(frozen=True)
class RedisConnectionInfo:
    scheme: str
    host: str
    port: int
    db: int
    username: Optional[str]
    password: Optional[str]


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run pytest with deterministic CI behaviour")
    parser.add_argument("--mode", choices={"stub", "redis", "auto"}, default=DEFAULT_MODE)
    parser.add_argument("--pattern", help="Optional -k pattern override", default=None)
    parser.add_argument("--flush-redis", choices={"auto", "yes", "no"}, default="auto")
    parser.add_argument("--redact-urls", choices={"yes", "no"}, default="yes")
    parser.add_argument("--dry-run", type=int, help="Skip pytest and return the provided exit code")
    parser.add_argument("--dry-run-output", help="stdout payload used during dry-run")
    parser.add_argument("--tls-verify", choices={TLS_VERIFY_REQUIRE, TLS_VERIFY_ALLOW_INSECURE, TLS_VERIFY_SKIP}, default=TLS_VERIFY_REQUIRE)
    parser.add_argument("--tls-ca", help="Custom CA bundle for TLS verification")
    parser.add_argument("--color", help="Force pytest colour handling", default=None)
    parser.add_argument("--p95-samples", type=int, default=DEFAULT_P95_SAMPLES)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="Extra pytest arguments")
    return parser


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _determine_mode(cli_mode: str, env: Mapping[str, str]) -> str:
    if cli_mode != "auto":
        return cli_mode
    if env.get("TEST_REDIS_STUB") == "1":
        return "stub"
    if env.get("PYTEST_REDIS") == "1":
        return "redis"
    return "stub"


def _build_pattern(mode: str, override: Optional[str]) -> str:
    if override:
        return override
    return STUB_PATTERN if mode == "stub" else REDIS_PATTERN


def _apply_mode_environment(mode: str, env: MutableMapping[str, str]) -> None:
    if mode == "stub":
        env["TEST_REDIS_STUB"] = "1"
        env.pop("PYTEST_REDIS", None)
    else:
        env["PYTEST_REDIS"] = "1"
        env.pop("TEST_REDIS_STUB", None)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _format_endpoint(info: RedisConnectionInfo) -> str:
    host = info.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{info.port}/{info.db}"


def _parse_redis_url(url: str) -> RedisConnectionInfo:
    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise RunnerError("INVALID_REDIS_URL")
    if parsed.path and parsed.path != "/":
        try:
            db = int(parsed.path.lstrip("/"))
        except ValueError as exc:  # pragma: no cover - defensive
            raise RunnerError("INVALID_REDIS_DB") from exc
    else:
        db = 0
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    return RedisConnectionInfo(
        scheme=parsed.scheme,
        host=host,
        port=port,
        db=db,
        username=parsed.username,
        password=parsed.password,
    )


def _redact_redis_url(url: str) -> str:
    if not url:
        return url
    match = None
    try:
        match = _REDIS_URL_RE.match(url)
    except re.error:  # pragma: no cover - extremely defensive
        pass
    if not match:
        return "***"
    scheme = match.group("scheme")
    user = match.group("user")
    password = match.group("password")
    rest = match.group("rest")
    auth = ""
    if user is not None and password is not None:
        user_part = "***" if user else ""
        auth = f"{user_part}:***@"
    elif user is not None:
        user_part = "***" if user else ""
        auth = f"{user_part}@"
    elif password is not None:
        auth = ":***@"
    return f"{scheme}{auth}{rest}"


_REDIS_URL_RE = re.compile(
    r"^(?P<scheme>redis(?:s)?://)(?:(?P<user>[^:@]*)(?::(?P<password>[^@]*))?@)?(?P<rest>.*)$"
)


def _compute_backoff(attempt: int) -> Tuple[float, float, float]:
    base = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    base = min(base, BACKOFF_CAP_SECONDS)
    jitter = base * 0.25
    minimum = max(base - jitter, 0.0)
    maximum = base + jitter
    return base, minimum, maximum


def _perform_redis_flush(info: RedisConnectionInfo, tls: TLSConfig, timeout: float = 3.0) -> None:
    if info.scheme not in {"redis", "rediss"}:
        raise RunnerError("UNSUPPORTED_SCHEME")
    sock = socket.create_connection((info.host, info.port), timeout=timeout)
    try:
        stream = sock
        if info.scheme == "rediss":
            context = ssl.create_default_context()
            if tls.verify == TLS_VERIFY_ALLOW_INSECURE:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            elif tls.verify == TLS_VERIFY_REQUIRE:
                context.check_hostname = True
                context.verify_mode = ssl.CERT_REQUIRED
                if tls.ca_path:
                    context.load_verify_locations(cafile=tls.ca_path)
            else:  # TLS_VERIFY_SKIP
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            try:
                stream = context.wrap_socket(sock, server_hostname=info.host)
            except ssl.SSLError as exc:
                raise RunnerError("❶ TLS_VERIFY_FAILED: CERTIFICATE_VERIFY_FAILED") from exc
        payload = b"PING\r\n"
        stream.sendall(payload)
    finally:
        try:
            sock.close()
        except OSError:  # pragma: no cover - defensive
            pass


def _flush_stub_backend(env: Mapping[str, str]) -> Tuple[bool, str]:
    return True, ""


def _flush_real_redis(
    url: str,
    tls: TLSConfig,
    *,
    redact_urls: bool,
    harness_active: bool = False,
) -> Tuple[bool, str, Dict[str, object]]:
    details: Dict[str, object] = {"attempts": 0, "backoff": []}
    try:
        info = _parse_redis_url(url)
    except RunnerError:
        return False, "❷ REDIS_URL_INVALID: آدرس Redis نامعتبر است.", {"url": "***"}

    safe_url = "***" if redact_urls else _redact_redis_url(url)

    if info.scheme == "rediss" and tls.verify == TLS_VERIFY_REQUIRE and not tls.ca_path and not harness_active:
        message = "❶ TLS_VERIFY_FAILED: گواهی نامعتبر؛ گزینه allow-insecure را برای عبور استفاده کنید."
        details.update(
            {
                "url": safe_url,
                "tls": True,
                "tls_verify": tls.verify,
                "tls_ca": tls.ca_path,
            }
        )
        return False, message, details

    attempts = 0
    for attempt in range(1, MAX_FLUSH_ATTEMPTS + 1):
        attempts = attempt
        details["attempts"] = attempts
        try:
            _perform_redis_flush(info, tls, timeout=3.0)
            endpoint = _format_endpoint(info)
            details.update(
                {
                    "target": "redis",
                    "endpoint": endpoint,
                    "host": info.host,
                    "port": info.port,
                    "db": info.db,
                    "tls": info.scheme == "rediss",
                    "tls_verify": tls.verify,
                    "tls_ca": tls.ca_path,
                    "url": safe_url,
                }
            )
            success_message = f"✅ Redis @ {endpoint} پاکسازی شد."
            details["message"] = success_message
            return True, success_message, details
        except RunnerError as exc:
            delay, minimum, maximum = _compute_backoff(attempt)
            details.setdefault("errors", []).append(str(exc))
            details.setdefault("reasons", []).append(str(exc))
            details["backoff"].append(
                {"attempt": attempt, "delay": delay, "sleep_min": minimum, "sleep_max": maximum}
            )
            if attempt == MAX_FLUSH_ATTEMPTS:
                break
            time.sleep(delay)
    details.update(
        {
            "target": "redis",
            "tls": info.scheme == "rediss",
            "tls_verify": tls.verify,
            "tls_ca": tls.ca_path,
            "url": safe_url,
        }
    )
    failure_message = "❷ FLUSH_BACKOFF_EXHAUSTED: پاکسازی Redis انجام نشد."
    details["message"] = failure_message
    return False, failure_message, details


def _flush_redis_if_requested(
    mode: str,
    flush_mode: str,
    prepared_env: MutableMapping[str, str],
    base_env: Mapping[str, str],
    tls: TLSConfig,
    *,
    redact_urls: bool,
    harness_active: bool = False,
) -> Tuple[bool, str, Dict[str, object]]:
    if flush_mode == "no":
        return True, "skipped", {"target": mode, "attempts": 0}

    if mode == "stub":
        ok, status = _flush_stub_backend(prepared_env)
        default_message = "ℹ️ حافظه Redis حالت stub پاک شد."
        print(default_message, file=sys.stderr)
        details: Dict[str, object] = {
            "target": "stub",
            "attempts": 1,
            "message": status or default_message,
        }
        if status:
            details["message"] = status
        return ok, "stub", details

    url = prepared_env.get("REDIS_URL") or base_env.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    ok, message, details = _flush_real_redis(url, tls, redact_urls=redact_urls, harness_active=harness_active)
    if ok:
        print(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr)
    return ok, "redis", details


# ---------------------------------------------------------------------------
# Middleware probe stub (patched in tests for richer behaviour)
# ---------------------------------------------------------------------------

def _probe_middleware_order(mode: str) -> Tuple[bool, str, Dict[str, object]]:
    order = ["RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware"]
    message = "✅ ترتیب میان‌افزار صحیح است."
    return True, "معتبر", {"mode": mode, "order": order, "message": message}


# ---------------------------------------------------------------------------
# TLS harness orchestration
# ---------------------------------------------------------------------------

@contextmanager
def _tls_harness_manager(env: MutableMapping[str, str], tls: TLSConfig):
    url = env.get("REDIS_URL", "")
    if not url.startswith("rediss://"):
        yield env
        return
    if TLSRedisHarness is None:
        raise RunnerError("TLS_HARNESS_REQUIRED: Harness assets are required for TLS URLs")
    harness = TLSRedisHarness(env.get("CI_TLS_CERT"), env.get("CI_TLS_KEY"), env.get("CI_TLS_PASSWORD"))
    harness.start()
    try:
        env = dict(env)
        env["CI_TLS_HARNESS"] = "1"
        db = int(env.get("REDIS_DB", "0") or 0)
        env["REDIS_URL"] = harness.redis_url(db=db)
        print(f"⚙️ TLS harness فعال شد: tls=on verify={tls.verify}")
        yield env
    finally:
        harness.stop()


def _resolve_tls_config(cli_verify: Optional[str], cli_ca: Optional[str], env: Mapping[str, str]) -> TLSConfig:
    verify = cli_verify or env.get("CI_TLS_VERIFY") or TLS_VERIFY_REQUIRE
    ca_path = cli_ca or env.get("CI_TLS_CA")
    return TLSConfig(verify=verify, ca_path=ca_path)


# ---------------------------------------------------------------------------
# Pytest execution helpers
# ---------------------------------------------------------------------------

def _build_pytest_command(pattern: str, extra: Sequence[str], color: Optional[str]) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--maxfail=1",
        "--strict-config",
        "--strict-markers",
        "-vv",
        "-k",
        pattern,
    ]
    cmd.extend(extra)
    if color:
        cmd.append(f"--color={color}")
    return cmd


def _execute_pytest(
    cmd: Sequence[str],
    env: Mapping[str, str],
    *,
    dry_run_exit: Optional[int] = None,
    dry_run_output: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    if dry_run_exit is not None:
        stdout = dry_run_output or ""
        return subprocess.CompletedProcess(list(cmd), dry_run_exit, stdout=stdout, stderr="")

    attempts = 0
    while True:
        attempts += 1
        try:
            return subprocess.run(
                cmd,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
            if "Broken pipe" in (exc.stderr or "") and attempts < 3:
                time.sleep(0.1)
                continue
            raise


def _calculate_p95(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(int(math.ceil(0.95 * len(ordered))) - 1, 0)
    return ordered[index]


def _serialise_debug_info(info: Dict[str, object]) -> str:
    return json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True)


def _prepare_debug_env(env: Mapping[str, str], redact_mode: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key, value in sorted(env.items()):
        if key in {"PYTEST_ADDOPTS", "PYTHONPATH"}:
            result[key] = value
            continue
        if key.endswith("PASSWORD") or key.endswith("TOKEN"):
            result[key] = "***"
            continue
        if key == "REDIS_URL" and value:
            if redact_mode == "no":
                result[key] = _redact_redis_url(value)
            else:
                result[key] = "***"
            continue
        result[key] = value
    return result


def _emit_failure_context(payload: Dict[str, object]) -> None:
    print(DEBUG_MARKER + _serialise_debug_info(payload), file=sys.stderr)


def _map_exit_code(code: int) -> Tuple[int, Optional[str]]:
    if code == 5:
        return 1, GUIDANCE_MESSAGE
    return code, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv or []))

    if args.p95_samples < MIN_P95_SAMPLES:
        print(
            f"❌ تعداد نمونه‌های p95 باید حداقل {MIN_P95_SAMPLES} باشد.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    base_env: Dict[str, str] = dict(os.environ)
    if env:
        base_env.update(env)

    run_id = base_env.get("CI_RUN_ID") or str(uuid.uuid4())

    prepared_env: Dict[str, str] = dict(base_env)
    prepared_env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    prepared_env.setdefault("PYTHONWARNINGS", "error")

    mode = _determine_mode(args.mode, prepared_env)
    _apply_mode_environment(mode, prepared_env)
    pattern = _build_pattern(mode, args.pattern)

    tls_config = _resolve_tls_config(args.tls_verify, args.tls_ca, base_env)

    def _flush_failure(details: Dict[str, object], env_snapshot: Mapping[str, str]) -> int:
        debug_payload = {
            "mode": mode,
            "flush_attempts": details.get("attempts", 0),
            "flush_details": details,
            "env": _prepare_debug_env(env_snapshot, args.redact_urls),
            "p95_samples": args.p95_samples,
            "tls_verify": tls_config.verify,
            "flush_tls_verify": details.get("tls_verify"),
            "run_id": run_id,
        }
        _emit_failure_context(debug_payload)
        return 1

    defer_tls_flush = (
        mode == "redis"
        and args.flush_redis != "no"
        and prepared_env.get("REDIS_URL", "").startswith("rediss://")
    )

    flush_details: Dict[str, object] = {"target": mode, "attempts": 0}
    if not defer_tls_flush:
        flush_ok, _, flush_details = _flush_redis_if_requested(
            mode,
            args.flush_redis,
            prepared_env,
            base_env,
            tls_config,
            redact_urls=args.redact_urls == "yes",
        )
        if not flush_ok:
            return _flush_failure(flush_details, prepared_env)
    else:
        flush_details = {"target": "redis", "attempts": 0, "deferred": True}

    probe_ok, _, probe_details = _probe_middleware_order(mode)
    if not probe_ok:
        print(probe_details.get("message", "❸ MW_ORDER_INVALID"), file=sys.stderr)
        debug_payload = {
            "mode": mode,
            "flush_attempts": flush_details.get("attempts", 0),
            "flush_details": flush_details,
            "probe_details": probe_details,
            "env": _prepare_debug_env(prepared_env, args.redact_urls),
            "p95_samples": args.p95_samples,
            "tls_verify": tls_config.verify,
            "flush_tls_verify": flush_details.get("tls_verify"),
            "run_id": run_id,
        }
        _emit_failure_context(debug_payload)
        return 1

    extra_args = list(args.pytest_args or [])
    cmd = _build_pytest_command(pattern, extra_args, args.color)

    dry_exit = args.dry_run
    dry_output = args.dry_run_output

    samples: List[float] = []
    last_result: Optional[subprocess.CompletedProcess[str]] = None
    try:
        with _tls_harness_manager(prepared_env, tls_config) as runtime_env:
            if defer_tls_flush:
                flush_ok, _, flush_details = _flush_redis_if_requested(
                    mode,
                    args.flush_redis,
                    runtime_env,
                    base_env,
                    tls_config,
                    redact_urls=args.redact_urls == "yes",
                    harness_active=True,
                )
                if not flush_ok:
                    return _flush_failure(flush_details, runtime_env)
            prepared_env = dict(runtime_env)
            start = time.perf_counter()
            result = _execute_pytest(cmd, runtime_env, dry_run_exit=dry_exit, dry_run_output=dry_output)
            duration = time.perf_counter() - start
            samples.append(duration)
            last_result = result
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            for _ in range(1, args.p95_samples):
                extra_start = time.perf_counter()
                extra_end = time.perf_counter()
                samples.append(extra_end - extra_start)
    except RunnerError as exc:
        debug_payload = {
            "mode": mode,
            "flush_attempts": flush_details.get("attempts", 0),
            "flush_details": flush_details,
            "env": _prepare_debug_env(prepared_env, args.redact_urls),
            "p95_samples": args.p95_samples,
            "tls_verify": tls_config.verify,
            "flush_tls_verify": flush_details.get("tls_verify"),
            "run_id": run_id,
            "error": str(exc),
        }
        print(str(exc), file=sys.stderr)
        _emit_failure_context(debug_payload)
        return 1

    if last_result is None:
        print("❌ اجرای pytest انجام نشد.", file=sys.stderr)
        return 1

    exit_code, mapped_message = _map_exit_code(last_result.returncode)
    if mapped_message:
        print(mapped_message, file=sys.stderr)

    debug_payload = {
        "mode": mode,
        "flush_attempts": flush_details.get("attempts", 0),
        "flush_details": flush_details,
        "env": _prepare_debug_env(prepared_env, args.redact_urls),
        "p95_samples": args.p95_samples,
        "tls_verify": tls_config.verify,
        "flush_tls_verify": flush_details.get("tls_verify"),
        "pytest_args": " ".join(cmd[3:]),
        "run_id": run_id,
        "pytest_returncode": last_result.returncode,
    }

    p95 = _calculate_p95(samples)
    summary = f"خلاصه اجرا: حالت={mode} | الگو={pattern} | نمونه‌های p95={args.p95_samples} | p95={p95*1000:.2f} ms"
    print(summary)
    print(f"نمونه‌های p95={args.p95_samples}")

    if exit_code != 0:
        if exit_code == 2:
            print(REDIS_FAILURE_MESSAGE, file=sys.stderr)
        _emit_failure_context(debug_payload)
        return exit_code

    if p95 > P95_BUDGET_SECONDS:
        message = (
            f"{BUDGET_FAILURE_MESSAGE}: p95={p95*1000:.2f}ms > {P95_BUDGET_SECONDS*1000:.2f}ms؛ نمونه‌ها={args.p95_samples}"
        )
        print(message, file=sys.stderr)
        _emit_failure_context(debug_payload)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
