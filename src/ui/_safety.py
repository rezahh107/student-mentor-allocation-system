"""Safety helpers for Qt UI flows."""
from __future__ import annotations

import logging
import os
from contextlib import ContextDecorator
from functools import wraps
from types import TracebackType
from typing import Any, Callable, Optional, Type, TypeVar, cast

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from prometheus_client import Counter as PrometheusCounter
except Exception:  # noqa: BLE001 - optional dependency may be missing
    PrometheusCounter = None

_UI_ERROR_COUNTER: Optional[Any] = None
if PrometheusCounter is not None:
    _UI_ERROR_COUNTER = PrometheusCounter(
        "smartalloc_ui_errors_total",
        "تعداد خطاهای بلعیده‌شده در رابط کاربری گرافیکی.",
        ["reason"],
    )

_UI_MINIMAL_FLAG = "UI_MINIMAL"


def is_minimal_mode() -> bool:
    """Return ``True`` when minimal UI mode is active."""

    return os.environ.get(_UI_MINIMAL_FLAG, "") == "1"


class _SwallowUIError(ContextDecorator):
    """Context manager/decorator that logs and optionally swallows UI errors."""

    def __init__(self, reason: str, fallback: Optional[Callable[[], None]] = None) -> None:
        self._reason = reason
        self._fallback = fallback

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        if exc_type is None or exc is None:
            return False

        LOGGER.exception("خطای رابط کاربری در «%s»: %s", self._reason, exc)
        if _UI_ERROR_COUNTER is not None:
            try:
                _UI_ERROR_COUNTER.labels(reason=self._reason).inc()
            except Exception:  # noqa: BLE001 - defensive
                LOGGER.debug("ثبت متریک رابط کاربری برای «%s» ناموفق بود.", self._reason)
        if self._fallback is not None:
            try:
                self._fallback()
            except Exception as fallback_exc:  # noqa: BLE001 - fallback should never break flow
                LOGGER.exception(
                    "اجرای fallback برای «%s» با خطا مواجه شد: %s", self._reason, fallback_exc
                )
                if _UI_ERROR_COUNTER is not None:
                    try:
                        _UI_ERROR_COUNTER.labels(reason=f"{self._reason}:fallback").inc()
                    except Exception:  # noqa: BLE001 - defensive
                        LOGGER.debug(
                            "ثبت متریک fallback برای «%s» ناموفق بود.", self._reason
                        )
        return True


def swallow_ui_error(reason: str, fallback: Optional[Callable[[], None]] = None) -> _SwallowUIError:
    """Return a context manager that swallows UI exceptions safely."""

    return _SwallowUIError(reason, fallback)


F = TypeVar("F", bound=Callable[..., object])


def ui_safe(reason: str, fallback: Optional[Callable[[], None]] = None) -> Callable[[F], F]:
    """Decorator applying :func:`swallow_ui_error` to functions."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):  # type: ignore[override]
            with swallow_ui_error(reason, fallback):
                return func(*args, **kwargs)
            return None

        return cast(F, wrapper)

    return decorator


def log_minimal_mode(component: str) -> None:
    """Log a Persian info message when minimal UI is active for a component."""

    LOGGER.info("حالت UI مینیمال فعال است؛ «%s» اجرا نمی‌شود.", component)
