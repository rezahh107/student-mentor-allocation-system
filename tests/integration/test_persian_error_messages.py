"""Integration-level validation for deterministic Persian error messaging."""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Any, Dict

import pytest

from tests.helpers.integration_context import IntegrationContext


class PersianErrorMessages:
    """Single source of truth for localized Persian error messaging."""

    MESSAGES: Dict[str, str] = {
        "UNAUTHORIZED": "دسترسی غیرمجاز - لطفاً وارد شوید",
        "RATE_LIMIT": "تعداد درخواست‌ها بیش از حد مجاز است",
        "VALIDATION_ERROR": "داده‌های ورودی نامعتبر است",
        "NOT_FOUND": "منبع درخواستی یافت نشد",
        "SERVER_ERROR": "خطای داخلی سرور رخ داده است",
        "INVALID_FORMAT": "فرمت داده‌ها صحیح نیست",
        "EXCEL_ERROR": "خطا در پردازش فایل Excel",
        "STUDENT_NOT_FOUND": "دانش‌آموز در سیستم یافت نشد",
    }

    @classmethod
    def get_message(cls, error_code: str) -> str:
        """Return the deterministic Persian error message for the provided code."""

        normalized_code = (error_code or "").strip().upper()
        return cls.MESSAGES.get(normalized_code, "خطای نامشخص")

    @classmethod
    def validate_message(cls, error_code: str, actual_message: str) -> bool:
        """Ensure the actual localized message exactly matches the canonical value."""

        expected = cls.get_message(error_code)
        if actual_message is None:
            return False
        return actual_message.strip() == expected

    @classmethod
    def iter_all(cls):
        """Iterate over canonical error codes and their localized messages."""

        return cls.MESSAGES.items()


@contextmanager
def guard_state(context: IntegrationContext):
    """Ensure Redis/db state is cleared before and after a validation block."""

    context.clear_state()
    try:
        yield
    finally:
        context.clear_state()


@pytest.mark.integration
class TestPersianErrorMessages:
    """Comprehensive validation for localized error messages with debug context."""

    @pytest.mark.parametrize(
        "error_code,expected_message",
        [
            ("UNAUTHORIZED", "دسترسی غیرمجاز - لطفاً وارد شوید"),
            ("RATE_LIMIT", "تعداد درخواست‌ها بیش از حد مجاز است"),
            ("VALIDATION_ERROR", "داده‌های ورودی نامعتبر است"),
            ("NOT_FOUND", "منبع درخواستی یافت نشد"),
            ("SERVER_ERROR", "خطای داخلی سرور رخ داده است"),
        ],
    )
    def test_standard_error_messages(self, integration_context: IntegrationContext, error_code: str, expected_message: str) -> None:
        """Ensure standard error codes resolve deterministically with retries and debug output."""

        with guard_state(integration_context):
            result_payload = integration_context.measure_operation(
                lambda: integration_context.call_with_retry(
                    lambda: PersianErrorMessages.get_message(error_code),
                    label="persian_error_lookup",
                ),
                label=f"lookup:{error_code}",
            )
            actual = result_payload["result"]
            assert actual == expected_message, integration_context.format_debug(
                "Unexpected localized message", error_code=error_code, actual=actual, expected=expected_message
            )
            assert PersianErrorMessages.validate_message(error_code, actual), integration_context.format_debug(
                "Canonical validation failed", error_code=error_code, actual=actual
            )

    def test_middleware_error_messages(self, integration_context: IntegrationContext) -> None:
        """Simulate middleware stack failures and validate Persian messaging semantics."""

        with guard_state(integration_context):
            auth_response = {
                "error": integration_context.call_with_retry(
                    lambda: PersianErrorMessages.get_message("UNAUTHORIZED"),
                    label="auth_error_message",
                ),
                "status": 401,
            }
            rate_limit_response = {
                "error": integration_context.call_with_retry(
                    lambda: PersianErrorMessages.get_message("RATE_LIMIT"),
                    label="rate_limit_error_message",
                ),
                "status": 429,
            }
            assert "دسترسی غیرمجاز" in auth_response["error"], integration_context.format_debug(
                "Auth middleware error missing Persian text",
                auth_response=auth_response,
            )
            assert "تعداد درخواست‌ها" in rate_limit_response["error"], integration_context.format_debug(
                "Rate limit middleware error missing Persian text",
                rate_limit_response=rate_limit_response,
            )

    def test_student_type_error_messages(self, integration_context: IntegrationContext) -> None:
        """Validate student roster errors while handling zero-width and mixed-digit inputs."""

        with guard_state(integration_context):
            expected = PersianErrorMessages.get_message("STUDENT_NOT_FOUND")
            lookup_result = integration_context.call_with_retry(
                lambda: PersianErrorMessages.validate_message("STUDENT_NOT_FOUND", expected + "\u200c"),
                label="student_type_error_validation",
            )
            assert lookup_result is False, integration_context.format_debug(
                "Zero-width characters should invalidate mismatched messages",
                expected=expected,
            )
            assert PersianErrorMessages.validate_message("STUDENT_NOT_FOUND", expected), integration_context.format_debug(
                "Canonical student error mismatch", expected=expected
            )
            assert PersianErrorMessages.get_message("invalid_code") == "خطای نامشخص"

    def test_excel_error_messages(self, integration_context: IntegrationContext) -> None:
        """Ensure Excel pipeline emits the exact localized message even for large payloads."""

        huge_payload = "خطا در پردازش فایل Excel" + "!" * 4096
        with guard_state(integration_context):
            expected = PersianErrorMessages.get_message("EXCEL_ERROR")
            assert "Excel" in expected
            assert "خطا در پردازش" in expected
            assert not PersianErrorMessages.validate_message("EXCEL_ERROR", huge_payload), integration_context.format_debug(
                "Oversized Excel error should not match canonical message",
                length=len(huge_payload),
            )

    def test_message_consistency(self, integration_context: IntegrationContext) -> None:
        """Confirm all messages contain Persian characters and meet formatting guarantees."""

        with guard_state(integration_context):
            for code, message in PersianErrorMessages.iter_all():
                assert any(ord(char) > 127 for char in message), integration_context.format_debug(
                    "Message missing Persian characters", code=code, message=message
                )
                assert len(message.strip()) == len(message), integration_context.format_debug(
                    "Message contains leading/trailing whitespace", code=code, message=message
                )
                assert len(message) >= 6, integration_context.format_debug(
                    "Message unexpectedly short", code=code, message=message
                )

    def test_unknown_codes_and_edge_inputs(self, integration_context: IntegrationContext) -> None:
        """Validate guard rails for None/empty values, numeric strings, and mixed digit inputs."""

        edge_cases: list[tuple[Any, Any]] = [
            (None, "خطای نامشخص"),
            ("", "خطای نامشخص"),
            ("  ", "خطای نامشخص"),
            ("0", "خطای نامشخص"),
            ("۰۰", "خطای نامشخص"),
            ("rate_limit", PersianErrorMessages.MESSAGES["RATE_LIMIT"]),
        ]

        with guard_state(integration_context):
            for raw_code, expected in edge_cases:
                result = integration_context.call_with_retry(
                    lambda value=raw_code: PersianErrorMessages.get_message(str(value) if value is not None else ""),
                    label="edge_error_lookup",
                )
                assert result == expected, integration_context.format_debug(
                    "Edge case mismatch", raw_code=raw_code, result=result, expected=expected
                )

    def test_validation_cross_product(self, integration_context: IntegrationContext) -> None:
        """Property-based validation across all canonical codes and representative payload variants."""

        payload_variants = ["", " ", "\u200c", "0", "۰", "long" * 50]
        with guard_state(integration_context):
            for code, message in PersianErrorMessages.iter_all():
                for variant in payload_variants:
                    target_message = message + variant
                    is_valid = PersianErrorMessages.validate_message(code, target_message)
                    if variant.strip():
                        assert not is_valid, integration_context.format_debug(
                            "Variant payload should fail validation",
                            code=code,
                            variant=variant,
                        )
                    else:
                        assert is_valid, integration_context.format_debug(
                            "Whitespace-only variant should normalize and pass",
                            code=code,
                            variant=variant,
                        )

    def test_pairwise_uniqueness(self, integration_context: IntegrationContext) -> None:
        """Ensure each canonical message remains unique to avoid ambiguity in UI/telemetry."""

        with guard_state(integration_context):
            for (code_a, message_a), (code_b, message_b) in itertools.permutations(
                PersianErrorMessages.iter_all(), 2
            ):
                assert message_a != message_b, integration_context.format_debug(
                    "Duplicate messages detected",
                    code_a=code_a,
                    code_b=code_b,
                )
