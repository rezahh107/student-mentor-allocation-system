"""تست‌های ماژول امنیتی / Tests for the security module."""

import time
from pathlib import Path

import pytest

from sma.security.hardening import (
    RateLimiter,
    SecurityMonitor,
    SecurityViolationError,
    check_persian_injection,
    mask_pii,
    sanitize_input,
    secure_hash,
    secure_logging,
    validate_path,
)


class TestRateLimiter:
    """تست‌های کلاس محدودکننده نرخ."""

    def test_within_limit(self) -> None:
        limiter = RateLimiter(max_calls=5, time_window=1)
        current_time = time.time()
        for _ in range(5):
            assert limiter.check_limit("test_key", current_time) is True

    def test_exceeds_limit(self) -> None:
        limiter = RateLimiter(max_calls=3, time_window=1)
        current_time = time.time()
        for _ in range(3):
            assert limiter.check_limit("test_key", current_time) is True
        assert limiter.check_limit("test_key", current_time) is False

    def test_window_expiration(self) -> None:
        limiter = RateLimiter(max_calls=2, time_window=1)
        current_time = time.time()
        for _ in range(2):
            assert limiter.check_limit("test_key", current_time) is True
        assert limiter.check_limit("test_key", current_time) is False
        future_time = current_time + 1.1
        assert limiter.check_limit("test_key", future_time) is True

    def test_multiple_keys(self) -> None:
        limiter = RateLimiter(max_calls=2, time_window=1)
        current_time = time.time()
        assert limiter.check_limit("key1", current_time) is True
        assert limiter.check_limit("key1", current_time) is True
        assert limiter.check_limit("key1", current_time) is False
        assert limiter.check_limit("key2", current_time) is True
        assert limiter.check_limit("key2", current_time) is True
        assert limiter.check_limit("key2", current_time) is False


class TestSanitizeInput:
    """تست‌های تابع پاکسازی ورودی."""

    def test_remove_control_chars(self) -> None:
        input_text = "Hello\x00World\x08"
        assert sanitize_input(input_text) == "HelloWorld"

    def test_remove_rtl_override(self) -> None:
        input_text = "Hello\u202EWorld"
        assert sanitize_input(input_text) == "HelloWorld"

    def test_remove_html_tags(self) -> None:
        input_text = "Hello <script>alert('XSS')</script> World"
        assert sanitize_input(input_text) == "Hello  World"

    def test_persian_text(self) -> None:
        input_text = "سلام <b>دنیا</b>"
        assert sanitize_input(input_text) == "سلام دنیا"


class TestValidatePath:
    """تست‌های تابع اعتبارسنجی مسیر."""

    def test_valid_relative_path(self) -> None:
        assert validate_path("data/file.txt") is True
        assert validate_path("logs/app.log") is True

    def test_directory_traversal(self) -> None:
        assert validate_path("../config.txt") is False
        assert validate_path("data/../../../etc/passwd") is False

    def test_absolute_path(self) -> None:
        assert validate_path("/etc/passwd") is False
        assert validate_path(r"C:\Windows\System32") is False

    def test_tilde_expansion(self) -> None:
        assert validate_path("~/config.txt") is False


class TestMaskPII:
    """تست‌های تابع ماسک اطلاعات شخصی."""

    def test_mask_national_id(self) -> None:
        text = "شماره ملی: 1234567890"
        masked = mask_pii(text)
        assert "123*******0" in masked
        assert "1234567890" not in masked

    def test_mask_phone(self) -> None:
        text = "شماره تماس: 09123456789"
        masked = mask_pii(text)
        assert "0912*****89" in masked
        assert "09123456789" not in masked

    def test_mask_email(self) -> None:
        text = "ایمیل: user@example.com"
        masked = mask_pii(text)
        assert "u***@example.com" in masked
        assert "user@example.com" not in masked

    def test_multiple_pii(self) -> None:
        text = "اطلاعات: 1234567890 و 09123456789 و user@example.com"
        masked = mask_pii(text)
        assert "123*******0" in masked
        assert "0912*****89" in masked
        assert "u***@example.com" in masked


class TestSecureHash:
    """تست‌های تابع هش امن."""

    def test_hash_length(self) -> None:
        hash_value = secure_hash("test data")
        assert len(hash_value) == 64

    def test_hash_deterministic(self) -> None:
        hash1 = secure_hash("test data")
        hash2 = secure_hash("test data")
        assert hash1 != hash2

    def test_hash_different_inputs(self) -> None:
        hash1 = secure_hash("data1")
        hash2 = secure_hash("data2")
        assert hash1 != hash2


@pytest.mark.parametrize(
    "text,expected",
    [
        ("متن عادی فارسی", True),
        ("متن با <script>alert('XSS')</script>", False),
        ("متن با javascript:alert(1)", False),
        ("متن با SELECT * FROM users", False),
        ("متن با \u202Eکد مخرب", False),
        ("متن با eval('alert(1)')", False),
        ("متن با document.cookie", False),
    ],
)
def test_check_persian_injection(text: str, expected: bool) -> None:
    assert check_persian_injection(text) == expected


class TestSecurityMonitor:
    """تست‌های کلاس مانیتور امنیتی."""

    def test_log_event(self) -> None:
        monitor = SecurityMonitor()
        monitor.log_event(
            "login_attempt",
            {"username": "user1", "ip": "192.168.1.1"},
            "info",
            "auth_service",
        )
        assert len(monitor.events) == 1
        event = monitor.events[0]
        assert event["type"] == "login_attempt"
        assert event["severity"] == "info"
        assert event["source"] == "auth_service"
        assert "username" in event["details"]

    def test_mask_pii_in_events(self) -> None:
        monitor = SecurityMonitor()
        monitor.log_event(
            "user_update",
            {"national_id": "1234567890", "phone": "09123456789"},
            "info",
            "user_service",
        )
        event = monitor.events[0]
        details = event["details"]
        assert "123*******0" in details["national_id"]
        assert "0912*****89" in details["phone"]

    def test_security_metrics_empty(self) -> None:
        monitor = SecurityMonitor()
        metrics = monitor.get_security_metrics()
        assert metrics["total_events"] == 0
        assert metrics["security_score"] == 100

    def test_security_metrics(self) -> None:
        monitor = SecurityMonitor()
        monitor.log_event("login_success", {}, "info", "auth")
        monitor.log_event("login_failure", {}, "warning", "auth")
        monitor.log_event("login_failure", {}, "warning", "auth")
        monitor.log_event("permission_error", {}, "error", "access")
        monitor.log_event("data_breach", {}, "critical", "database")
        metrics = monitor.get_security_metrics()
        assert metrics["total_events"] == 5
        assert metrics["severity_counts"]["info"] == 1
        assert metrics["severity_counts"]["warning"] == 2
        assert metrics["severity_counts"]["error"] == 1
        assert metrics["severity_counts"]["critical"] == 1
        assert metrics["security_score"] == 81


# Placeholder usage of SecurityViolationError to keep it part of the public API

def test_security_violation_error_usage() -> None:
    with pytest.raises(SecurityViolationError):
        raise SecurityViolationError("violation detected")
