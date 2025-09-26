import os
import socket
import ssl
import subprocess
from pathlib import Path
from typing import List

import pytest

import tools.ci_pytest_runner as runner
from tests.ci.tls_harness import TLSRedisHarness


CI_REDIS = os.getenv("CI_REDIS") == "1"
CI_TLS_HARNESS = os.getenv("CI_TLS_HARNESS") == "1"

CERT_DIR = Path(__file__).parent / "certs"


def _dbsize(url: str) -> int:
    info = runner._parse_redis_url(url)
    raw_sock = socket.create_connection((info.host, info.port), timeout=5)
    sock = raw_sock
    try:
        if info.scheme == "rediss":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(raw_sock, server_hostname=info.host)
        sock.settimeout(5)
        if info.password is not None:
            if info.username:
                sock.sendall(runner._encode_redis_command("AUTH", info.username, info.password))
            else:
                sock.sendall(runner._encode_redis_command("AUTH", info.password))
            runner._read_redis_line(sock)
        sock.sendall(runner._encode_redis_command("SELECT", str(info.db)))
        runner._read_redis_line(sock)
        sock.sendall(runner._encode_redis_command("DBSIZE"))
        response = runner._read_redis_line(sock)
        if response.startswith(b":"):
            return int(response[1:].strip() or b"0")
        raise RuntimeError(response.decode("utf-8", "ignore"))
    finally:
        try:
            sock.close()
        finally:
            if sock is not raw_sock:
                raw_sock.close()


@pytest.fixture(scope="session")
def tls_harness():
    if not CI_TLS_HARNESS:
        raise RuntimeError("CI_TLS_HARNESS فعال نیست؛ برای اجرای تست TLS این متغیر باید روی ۱ تنظیم شود")
    harness = TLSRedisHarness(
        str(CERT_DIR / "harness.pem"),
        str(CERT_DIR / "harness.key"),
        password="ci-harness-secret",
    )
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


@pytest.fixture
def harness_env(monkeypatch, tls_harness):
    ca_path = CERT_DIR / "ci-ca.pem"
    url = tls_harness.redis_url()
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setenv("PYTEST_REDIS", "1")
    monkeypatch.setenv("CI_TLS_CA", str(ca_path))
    return {
        "mode": "redis",
        "expect_available": True,
        "tls_config": runner.TLSConfig(ca_path=str(ca_path)),
        "harness": tls_harness,
    }


@pytest.fixture
def harness_env_failure(tls_harness):
    return {"harness": tls_harness}


@pytest.fixture
def redis_live_env():
    if not CI_REDIS:
        raise RuntimeError("CI_REDIS فعال نیست؛ این تست تنها در محیط CI با Redis واقعی اجرا می‌شود")
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("برای اجرای تست زنده باید REDIS_URL تنظیم شود")
    return {"mode": "redis", "expect_available": True}


@pytest.fixture(autouse=True)
def ci_state_autoflush(request):
    context = {}
    for candidate in ("harness_env_failure", "harness_env", "redis_live_env"):
        if candidate in request.fixturenames:
            context = request.getfixturevalue(candidate) or {}
            break

    if request.node.get_closest_marker("force_skip_cleanup"):
        yield
        return

    mode = context.get("mode") or runner._determine_mode("auto", os.environ)
    base_env = os.environ.copy()
    prepared_env = runner._apply_mode_env(mode, base_env)
    tls_config = context.get("tls_config") or runner._resolve_tls_config(
        runner.TLS_VERIFY_REQUIRE,
        None,
        base_env,
    )

    ok_before, _, details_before = runner._flush_redis_if_requested(
        mode,
        "auto",
        prepared_env,
        base_env,
        tls_config,
        redact_urls=True,
    )
    if context.get("expect_available") and not ok_before:
        pytest.fail(f"پاکسازی اولیه ناموفق بود: {details_before.get('message')}")

    yield

    ok_after, _, details_after = runner._flush_redis_if_requested(
        mode,
        "auto",
        prepared_env,
        base_env,
        tls_config,
        redact_urls=True,
    )
    if context.get("expect_available") and not ok_after:
        pytest.fail(f"پاکسازی پایانی ناموفق بود: {details_after.get('message')}")

    harness = context.get("harness")
    if harness is not None:
        assert harness.dbsize() == 0, "پایان تست باید بدون کلید باقی بماند"


@pytest.mark.xfail(not CI_REDIS, reason="CI_REDIS فعال نیست؛ این آزمون زنده فقط در CI اجرا می‌شود", strict=False)
def test_live_redis_flush_clears_db(redis_live_env):
    url = os.environ.get("REDIS_URL")
    ok, message, details = runner._flush_real_redis(
        url,
        runner.TLSConfig(),
        redact_urls=True,
    )
    assert ok, message
    assert details["attempts"] >= 1
    assert _dbsize(url) == 0


@pytest.mark.xfail(
    not CI_TLS_HARNESS,
    reason="CI_TLS_HARNESS فعال نیست؛ برای تست rediss باید این متغیر را روی ۱ بگذارید",
    strict=False,
)
def test_tls_harness_allow_insecure_flush(tls_harness, harness_env_failure):
    url = tls_harness.redis_url()
    ok, message, details = runner._flush_real_redis(
        url,
        runner.TLSConfig(verify=runner.TLS_VERIFY_ALLOW_INSECURE),
        redact_urls=True,
    )
    assert ok, message
    assert details["tls"] is True
    assert details["tls_verify"] == runner.TLS_VERIFY_ALLOW_INSECURE


@pytest.mark.xfail(
    not CI_TLS_HARNESS,
    reason="CI_TLS_HARNESS فعال نیست؛ برای تست rediss باید این متغیر را روی ۱ بگذارید",
    strict=False,
)
def test_tls_harness_requires_ca_failure(tls_harness, harness_env_failure):
    url = tls_harness.redis_url()
    ok, message, details = runner._flush_real_redis(
        url,
        runner.TLSConfig(verify=runner.TLS_VERIFY_REQUIRE),
        redact_urls=True,
    )
    assert not ok
    assert message.startswith("❷ FLUSH_BACKOFF_EXHAUSTED")
    assert any("❶ TLS_VERIFY_FAILED" in reason for reason in details["reasons"])


@pytest.mark.xfail(
    not CI_TLS_HARNESS,
    reason="CI_TLS_HARNESS فعال نیست؛ برای تست rediss باید این متغیر را روی ۱ بگذارید",
    strict=False,
)
def test_tls_harness_requires_ca_success(harness_env, tls_harness):
    url = os.environ["REDIS_URL"]
    tls_config = runner.TLSConfig(
        verify=runner.TLS_VERIFY_REQUIRE,
        ca_path=str(CERT_DIR / "ci-ca.pem"),
    )
    ok, message, details = runner._flush_real_redis(
        url,
        tls_config,
        redact_urls=True,
    )
    assert ok, message
    assert details["tls_verify"] == runner.TLS_VERIFY_REQUIRE
    assert details["tls_ca"].endswith("ci-ca.pem")
    assert _dbsize(url) == 0


@pytest.mark.xfail(
    not CI_TLS_HARNESS,
    reason="CI_TLS_HARNESS فعال نیست؛ برای تست rediss باید این متغیر را روی ۱ بگذارید",
    strict=False,
)
def test_autouse_cleanup_removes_keys(harness_env, tls_harness):
    tls_harness.set_key("autouse-key", "value")
    assert tls_harness.dbsize() == 1
    ok, _, _ = runner._flush_real_redis(
        os.environ["REDIS_URL"],
        runner.TLSConfig(
            verify=runner.TLS_VERIFY_REQUIRE,
            ca_path=os.environ.get("CI_TLS_CA"),
        ),
        redact_urls=True,
    )
    assert ok
    assert tls_harness.dbsize() == 0


def test_runner_auto_harness_end_to_end(monkeypatch, capsys):
    starts: List[str] = []
    original_cls = runner.TLSRedisHarness

    class TrackingHarness(original_cls):  # type: ignore[misc]
        def start(self):
            starts.append("start")
            super().start()

        def stop(self):
            starts.append("stop")
            super().stop()

    monkeypatch.setattr(runner, "TLSRedisHarness", TrackingHarness)

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(
        ["--mode", "auto", "--p95-samples", "3", "--flush-redis", "yes"],
        env={"REDIS_URL": "rediss://:ci-harness-secret@localhost:0/0"},
    )

    assert exit_code == 0
    assert starts.count("start") == 1
    assert starts.count("stop") == 1
    output = capsys.readouterr()
    assert "tls=on" in output.out
    assert "verify=require" in output.out


def test_runner_rediss_require_ca_fail_fast(monkeypatch, capsys):
    called = False

    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(
        ["--mode", "redis", "--p95-samples", "3", "--flush-redis", "yes"],
        env={"REDIS_URL": "rediss://:ci-harness-secret@localhost:0/0", "CI_TLS_HARNESS": "1"},
    )

    assert exit_code == 1
    assert called is False
    captured = capsys.readouterr()
    assert "TLS_VERIFY_FAILED" in captured.err


@pytest.mark.xfail(
    not CI_TLS_HARNESS,
    reason="CI_TLS_HARNESS فعال نیست؛ برای تست rediss باید این متغیر را روی ۱ بگذارید",
    strict=False,
)
def test_runner_rediss_allow_insecure_passes(monkeypatch, tls_harness, capsys):
    def fake_execute(cmd, env, dry_run_exit=None, dry_run_output=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="collected 1 items\n", stderr="")

    monkeypatch.setattr(runner, "_execute_pytest", fake_execute)

    exit_code = runner.main(
        [
            "--mode",
            "redis",
            "--p95-samples",
            "3",
            "--flush-redis",
            "yes",
            "--tls-verify",
            runner.TLS_VERIFY_ALLOW_INSECURE,
        ],
        env={"REDIS_URL": tls_harness.redis_url(), "CI_TLS_HARNESS": "1"},
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tls=on" in captured.out
    assert "verify=allow-insecure" in captured.out
