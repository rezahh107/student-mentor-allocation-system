import json
import socket
import subprocess
import sys
from typing import Dict, List

import pytest

import tools.ci_pytest_runner as runner


def _setup_success(monkeypatch):
    def fake_flush(mode, flush_mode, prepared_env, base_env, tls, **kwargs):
        return True, "stub", {
            "mode": flush_mode,
            "target": "stub",
            "message": "ok",
            "attempts": 1,
        }

    def fake_probe(mode):
        return True, "معتبر", {"mode": mode, "status": "valid", "message": "پروب موفق"}

    monkeypatch.setattr(runner, "_flush_redis_if_requested", fake_flush)
    monkeypatch.setattr(runner, "_probe_middleware_order", fake_probe)


@pytest.mark.parametrize(
    "mode, override, expected",
    [
        ("stub", None, runner.STUB_PATTERN),
        ("redis", None, runner.REDIS_PATTERN),
        ("stub", "custom", "custom"),
    ],
)
def test_pattern_selection(mode, override, expected):
    assert runner._build_pattern(mode, override) == expected


@pytest.mark.parametrize(
    "cli_mode, env, expected",
    [
        ("stub", {"TEST_REDIS_STUB": "0"}, "stub"),
        ("redis", {"TEST_REDIS_STUB": "1"}, "redis"),
        ("auto", {"TEST_REDIS_STUB": "1"}, "stub"),
        ("auto", {"PYTEST_REDIS": "1"}, "redis"),
        ("auto", {}, "stub"),
    ],
)
def test_mode_resolution(cli_mode, env, expected):
    assert runner._determine_mode(cli_mode, env) == expected


@pytest.mark.parametrize("mode, expected_var", [("stub", "TEST_REDIS_STUB"), ("redis", "PYTEST_REDIS")])
def test_environment_application(monkeypatch, mode, expected_var):
    _setup_success(monkeypatch)

    captured_env: Dict[str, str] = {}

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        nonlocal captured_env
        captured_env = dict(env)
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(["--mode", mode, "--p95-samples", "3"], env={})
    assert exit_code == 0
    assert captured_env[expected_var] == "1"
    other_var = "PYTEST_REDIS" if expected_var == "TEST_REDIS_STUB" else "TEST_REDIS_STUB"
    assert captured_env.get(other_var) != "1"
    assert captured_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_exit_code_mapping_and_guidance(monkeypatch, capsys):
    _setup_success(monkeypatch)

    code = runner.main(["--mode", "stub", "--dry-run", "5"], env={})
    captured = capsys.readouterr()
    assert code == 1
    assert runner.GUIDANCE_MESSAGE in captured.err


def test_cli_overrides_env(monkeypatch):
    _setup_success(monkeypatch)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 2 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(["--mode", "redis", "--p95-samples", "4"], env={"TEST_REDIS_STUB": "1"})
    assert exit_code == 0


def test_redis_failure_guidance(monkeypatch, capsys):
    _setup_success(monkeypatch)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 2, stdout="collected 1 items\n", stderr="redis failure")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    code = runner.main(["--mode", "redis", "--p95-samples", "3"], env={})
    captured = capsys.readouterr()
    assert code == 2
    assert runner.REDIS_FAILURE_MESSAGE in captured.err


def test_dry_run_allows_custom_output(monkeypatch, capsys):
    _setup_success(monkeypatch)

    code = runner.main(
        [
            "--mode",
            "stub",
            "--dry-run",
            "0",
            "--dry-run-output",
            "collected 3 items\n",
            "--p95-samples",
            "3",
        ],
        env={},
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "collected 3 items" in captured.out
    assert "خلاصه اجرا" in captured.out
    assert "نمونه‌های p95" in captured.out


def test_debug_information_respects_redact_toggle(monkeypatch, capsys):
    def fake_flush(mode, flush_mode, prepared_env, base_env, tls, **kwargs):
        return False, "redis-ناموفق", {
            "mode": flush_mode,
            "target": "redis",
            "message": "failed",
            "attempts": 1,
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "tls": False,
            "tls_verify": tls.verify,
            "tls_ca": tls.ca_path,
            "url": runner._redact_redis_url(prepared_env.get("REDIS_URL", "")),
        }

    monkeypatch.setattr(runner, "_flush_redis_if_requested", fake_flush)

    code = runner.main(
        [
            "--mode",
            "redis",
            "--flush-redis",
            "yes",
            "--redact-urls",
            "no",
            "--p95-samples",
            "3",
        ],
        env={"REDIS_URL": "redis://user:secret@localhost:6379/0"},
    )

    assert code == 1
    captured = capsys.readouterr()
    marker = "جزئیات اشکال:\n"
    payload = captured.err.split(marker, 1)[1]
    debug_json = json.loads(payload)
    assert debug_json["env"]["REDIS_URL"] == "redis://***:***@localhost:6379/0"
    assert debug_json.get("flush_tls_verify") == runner.TLS_VERIFY_REQUIRE


def test_debug_information_printed_on_failure(monkeypatch, capsys):
    _setup_success(monkeypatch)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 2, stdout="collected 1 items\n", stderr="failure details")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    code = runner.main(["--mode", "stub"], env={"REDIS_URL": "redis://user:secret@localhost:6379/0"})
    captured = capsys.readouterr()
    assert code == 2
    assert "جزئیات اشکال" in captured.err
    marker = "جزئیات اشکال:\n"
    payload = captured.err.split(marker, 1)[1]
    debug_json = json.loads(payload)
    assert debug_json["mode"] == "stub"
    assert "--strict-markers" in debug_json["pytest_args"]
    assert debug_json["flush_attempts"] == 1
    assert debug_json["p95_samples"] == runner.DEFAULT_P95_SAMPLES
    assert debug_json["env"]["REDIS_URL"] == "***"
    assert debug_json.get("flush_tls_verify") is None
    assert debug_json.get("run_id") is not None
    assert debug_json.get("tls_verify") == runner.TLS_VERIFY_REQUIRE


def test_color_argument_propagates(monkeypatch):
    _setup_success(monkeypatch)
    observed_cmd = None

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        nonlocal observed_cmd
        observed_cmd = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    runner.main(["--mode", "redis", "--color", "yes", "--p95-samples", "3"], env={})
    assert observed_cmd[-1] == "--color=yes"


def test_tls_verify_require_without_ca_fails_fast():
    url = "rediss://:secret@localhost:6380/0"
    ok, message, details = runner._flush_real_redis(
        url,
        runner.TLSConfig(verify=runner.TLS_VERIFY_REQUIRE, ca_path=None),
        redact_urls=True,
    )
    assert not ok
    assert message.startswith("❶ TLS_VERIFY_FAILED")
    assert "allow-insecure" in message
    assert details["tls"] is True
    assert details["tls_verify"] == runner.TLS_VERIFY_REQUIRE


def test_ipv6_endpoint_formatting(monkeypatch):
    calls: List[str] = []

    def fake_perform(info, tls, timeout=3.0):
        calls.append(runner._format_endpoint(info))

    monkeypatch.setattr(runner, "_perform_redis_flush", fake_perform)
    ok, message, details = runner._flush_real_redis(
        "redis://[::1]:6380/15",
        runner.TLSConfig(),
        redact_urls=True,
    )
    assert ok, message
    assert details["endpoint"] == "[::1]:6380/15"
    assert calls == ["[::1]:6380/15"]


def test_tls_harness_manager_requires_assets(monkeypatch):
    monkeypatch.setattr(runner, "TLSRedisHarness", None)
    env = {"REDIS_URL": "rediss://:s@localhost:6379/0"}
    with pytest.raises(runner.RunnerError) as excinfo:
        with runner._tls_harness_manager(env, runner.TLSConfig()) as _:
            pass
    assert "TLS_HARNESS_REQUIRED" in str(excinfo.value)


def test_runner_auto_starts_tls_harness(monkeypatch, capsys):
    instances: List[object] = []

    class FakeHarness:
        def __init__(self, cert_path, key_path, password):
            self.cert_path = cert_path
            self.key_path = key_path
            self.password = password
            self.port = 46379
            self.started = False
            self.stopped = False
            instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def redis_url(self, *, db=0, include_auth=True):
            auth = ":ci-harness-secret@" if include_auth else ""
            return f"rediss://{auth}localhost:{self.port}/{db}"

    monkeypatch.setattr(runner, "TLSRedisHarness", FakeHarness)

    captured_env: Dict[str, str] = {}

    def fake_flush(info, tls, timeout=3.0):
        return None

    monkeypatch.setattr(runner, "_perform_redis_flush", fake_flush)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        captured_env.update(env)
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(
        ["--mode", "redis", "--p95-samples", "3", "--flush-redis", "yes"],
        env={"REDIS_URL": "rediss://:secret@localhost:0/0"},
    )

    assert exit_code == 0
    assert instances and instances[0].started and instances[0].stopped
    assert captured_env.get("CI_TLS_HARNESS") == "1"
    assert captured_env.get("REDIS_URL", "").startswith("rediss://")
    out = capsys.readouterr().out
    assert "tls=on" in out
    assert "verify=require" in out


def test_tls_cli_options_propagate(monkeypatch):
    captured = {}

    def fake_flush(mode, flush_mode, prepared_env, base_env, tls, **kwargs):
        captured["verify"] = tls.verify
        captured["ca"] = tls.ca_path
        return True, "stub", {
            "mode": flush_mode,
            "target": "stub",
            "message": "ok",
            "attempts": 1,
        }

    monkeypatch.setattr(runner, "_flush_redis_if_requested", fake_flush)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(
        [
            "--mode",
            "stub",
            "--tls-verify",
            runner.TLS_VERIFY_ALLOW_INSECURE,
            "--tls-ca",
            "tests/ci/certs/ci-ca.pem",
            "--p95-samples",
            "3",
        ],
        env={},
    )

    assert exit_code == 0
    assert captured["verify"] == runner.TLS_VERIFY_ALLOW_INSECURE
    assert captured["ca"] == "tests/ci/certs/ci-ca.pem"


def test_retry_epipe(monkeypatch):
    _setup_success(monkeypatch)
    calls = {"count": 0}

    def fake_run(cmd, check, text, capture_output, env):
        calls["count"] += 1
        if calls["count"] < 2:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output="", stderr="Broken pipe")
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner.main(["--mode", "stub", "--p95-samples", "3"], env={})
    assert exit_code == 0
    assert calls["count"] == 2


def test_flush_stub_auto(monkeypatch, capsys):
    monkeypatch.setattr(runner, "_probe_middleware_order", lambda mode: (True, "معتبر", {"mode": mode}))

    stub_calls = {"count": 0}

    def fake_backend(env):
        stub_calls["count"] += 1
        return True, "stub flushed"

    monkeypatch.setattr(runner, "_flush_stub_backend", fake_backend)

    ok, status, details = runner._flush_redis_if_requested(
        "stub",
        "auto",
        {"TEST_REDIS_STUB": "1"},
        {},
        runner.TLSConfig(),
        redact_urls=True,
    )

    captured = capsys.readouterr()
    assert ok
    assert status == "stub"
    assert details["target"] == "stub"
    assert details["attempts"] == 1
    assert stub_calls["count"] == 1
    assert "حافظه Redis حالت stub پاک شد" in captured.err


def test_flush_real_retry_and_backoff(monkeypatch):
    attempts: List[int] = []
    sleeps: List[float] = []

    def fake_perform(info, tls, timeout):
        attempts.append(info.db)
        raise runner.RunnerError("AUTH failed")

    monkeypatch.setattr(runner, "_perform_redis_flush", fake_perform)
    monkeypatch.setattr(runner.time, "sleep", lambda value: sleeps.append(value))

    ok, message, details = runner._flush_real_redis(
        "redis://user:pass@localhost:6379/1",
        runner.TLSConfig(),
        redact_urls=True,
    )
    assert not ok
    assert message.startswith("❷ FLUSH_BACKOFF_EXHAUSTED")
    assert details["attempts"] == runner.MAX_FLUSH_ATTEMPTS
    assert len(details["reasons"]) == runner.MAX_FLUSH_ATTEMPTS
    assert details["tls_verify"] == runner.TLS_VERIFY_REQUIRE
    assert details["url"] == "***"
    for recorded, meta in zip(sleeps, details["backoff"]):
        assert recorded == pytest.approx(meta["delay"], rel=1e-6)


def test_flush_real_success_details(monkeypatch):
    seen = {}

    def fake_perform(info, tls, timeout):
        seen["host"] = info.host
        seen["port"] = info.port
        seen["db"] = info.db
        seen["tls"] = info.scheme
        return None

    monkeypatch.setattr(runner, "_perform_redis_flush", fake_perform)

    ok, message, details = runner._flush_real_redis(
        "rediss://user:pass@127.0.0.1:6380/2",
        runner.TLSConfig(verify=runner.TLS_VERIFY_ALLOW_INSECURE),
        redact_urls=False,
    )
    assert ok
    assert "127.0.0.1:6380/2" in message
    assert details["tls"]
    assert details["host"] == "127.0.0.1"
    assert details["db"] == 2
    assert details["url"].startswith("rediss://")
    assert details["tls_verify"] == runner.TLS_VERIFY_ALLOW_INSECURE
    assert details["tls_ca"] is None
    assert seen["tls"] == "rediss"


def test_flush_real_invalid_url():
    ok, message, details = runner._flush_real_redis(
        "ftp://example.com",
        runner.TLSConfig(),
        redact_urls=True,
    )
    assert not ok
    assert "آدرس Redis" in message
    assert details["url"] == "***"


def test_resolve_tls_config_uses_env():
    config = runner._resolve_tls_config(
        runner.TLS_VERIFY_REQUIRE,
        None,
        {"CI_TLS_CA": "/tmp/ci-ca.pem"},
    )
    assert config.ca_path == "/tmp/ci-ca.pem"
    assert config.verify == runner.TLS_VERIFY_REQUIRE

    config_cli = runner._resolve_tls_config(
        runner.TLS_VERIFY_ALLOW_INSECURE,
        "custom.pem",
        {},
    )
    assert config_cli.verify == runner.TLS_VERIFY_ALLOW_INSECURE
    assert config_cli.ca_path == "custom.pem"


def test_tls_verification_failure_message(monkeypatch):
    class DummySocket:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    dummy_socket = DummySocket()

    monkeypatch.setattr(
        runner.socket,
        "create_connection",
        lambda *args, **kwargs: dummy_socket,
    )

    class DummyContext:
        def __init__(self) -> None:
            self.check_hostname = None
            self.verify_mode = None

        def load_verify_locations(self, cafile: str | None = None) -> None:
            pass

        def wrap_socket(self, raw, server_hostname=None):  # pragma: no cover - simple stub
            raise runner.ssl.SSLError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(runner.ssl, "create_default_context", lambda: DummyContext())

    info = runner.RedisConnectionInfo("rediss", "localhost", 6380, 0, None, None)
    with pytest.raises(runner.RunnerError) as exc:
        runner._perform_redis_flush(info, runner.TLSConfig())

    assert "❶ TLS_VERIFY_FAILED" in str(exc.value)


def test_parse_redis_url_variants():
    info = runner._parse_redis_url("redis://user:pass@localhost:6379/5")
    assert info.username == "user"
    assert info.password == "pass"
    assert info.db == 5

    info_tls = runner._parse_redis_url("rediss://:secret@[::1]:6380/0")
    assert info_tls.scheme == "rediss"
    assert info_tls.host == "::1"
    assert info_tls.password == "secret"
    assert info_tls.db == 0

    with pytest.raises(runner.RunnerError):
        runner._parse_redis_url("redis://localhost/not-number")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("redis://user:pass@host:6379/0", "redis://***:***@host:6379/0"),
        ("redis://:pass@host:6379/0", "redis://:***@host:6379/0"),
        ("redis://host:6379/0", "redis://host:6379/0"),
        ("rediss://user@host", "rediss://***@host"),
    ],
)
def test_redact_redis_url(url, expected):
    assert runner._redact_redis_url(url) == expected


def test_compute_backoff_sequence_deterministic():
    values = [runner._compute_backoff(i) for i in range(1, runner.MAX_FLUSH_ATTEMPTS)]
    assert values[0][0] == pytest.approx(runner.BACKOFF_BASE_SECONDS)
    assert values[0][2] <= runner.BACKOFF_CAP_SECONDS
    assert values[1][0] >= values[0][0]


def test_probe_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        runner,
        "_flush_redis_if_requested",
        lambda mode, fm, env, base, tls, **kwargs: (True, "stub", {"target": "stub"}),
    )

    def fake_probe(mode):
        message = "❸ MW_ORDER_INVALID: ترتیب غلط"
        print(message, file=sys.stderr)
        print("کد خطا: MW_ORDER_INVALID", file=sys.stderr)
        return False, "نامعتبر", {"mode": mode, "message": message, "order": ["IdempotencyMiddleware", "RateLimitMiddleware"]}

    monkeypatch.setattr(runner, "_probe_middleware_order", fake_probe)

    code = runner.main(["--mode", "stub", "--p95-samples", "3"], env={})
    captured = capsys.readouterr()
    assert code == 1
    assert "کد خطا: MW_ORDER_INVALID" in captured.err
    assert "❸ MW_ORDER_INVALID" in captured.err
    assert "ترتیب غلط" in captured.err


def test_overhead_budget_failure(monkeypatch, capsys):
    _setup_success(monkeypatch)

    values = iter([0.0, 0.05, 0.1, 0.2, 0.3, 0.55])
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(values))

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    code = runner.main(["--mode", "stub", "--p95-samples", "3"], env={})
    captured = capsys.readouterr()
    assert code == 1
    assert "❺ BUDGET_P95_EXCEEDED" in captured.err
    assert "نمونه‌ها=3" in captured.err


def test_overhead_budget_success(monkeypatch, capsys):
    _setup_success(monkeypatch)

    values = iter([0.0, 0.01, 0.1, 0.11, 0.2, 0.21])
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(values))

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    code = runner.main(["--mode", "stub", "--p95-samples", "3"], env={})
    captured = capsys.readouterr()
    assert code == 0
    assert "هزینه اجرای رانر" not in captured.err


def test_p95_sample_size_enforced(monkeypatch, capsys):
    _setup_success(monkeypatch)
    with pytest.raises(SystemExit):
        runner.main(["--mode", "stub", "--p95-samples", "2"], env={})

    captured = capsys.readouterr()
    assert str(runner.MIN_P95_SAMPLES) in captured.err


def test_summary_includes_samples(monkeypatch, capsys):
    _setup_success(monkeypatch)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 4 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    runner.main(["--mode", "redis", "--p95-samples", "7"], env={})
    captured = capsys.readouterr()
    assert "نمونه‌های p95=7" in captured.out


def test_p95_sampling_with_custom_count(monkeypatch, capsys):
    _setup_success(monkeypatch)

    values = iter(
        [
            0.0,
            0.01,
            0.1,
            0.11,
            0.2,
            0.21,
            0.3,
            0.31,
            0.4,
            0.41,
            0.5,
            0.51,
            0.6,
            0.61,
        ]
    )
    monkeypatch.setattr(runner.time, "perf_counter", lambda: next(values))

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    code = runner.main(["--mode", "stub", "--p95-samples", "7"], env={})
    assert code == 0


def test_exit_code_five_maps_to_one(monkeypatch, capsys):
    _setup_success(monkeypatch)

    code = runner.main(["--mode", "redis", "--dry-run", "5", "--p95-samples", "3"], env={})
    assert code == 1
    assert runner.GUIDANCE_MESSAGE in capsys.readouterr().err
