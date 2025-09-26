"""Middleware probe utilities for validating FastAPI middleware order."""
from __future__ import annotations

import importlib
from typing import Any, Dict, List, Tuple

TARGET_MODULE = "src.api.api"
TARGET_FACTORY = "create_app"
RATE_LIMIT_MIDDLEWARE = "RateLimitMiddleware"
IDEMPOTENCY_MIDDLEWARE = "IdempotencyMiddleware"


def _load_factory() -> Tuple[Any, Dict[str, Any]]:
    details: Dict[str, Any] = {
        "module": TARGET_MODULE,
        "factory": TARGET_FACTORY,
    }
    try:
        module = importlib.import_module(TARGET_MODULE)
    except ModuleNotFoundError as exc:
        details.update({"status": "module-missing", "message": f"ماژول {TARGET_MODULE} یافت نشد: {exc}"})
        return None, details
    factory = getattr(module, TARGET_FACTORY, None)
    if factory is None:
        details.update({"status": "factory-missing", "message": f"تابع {TARGET_FACTORY} در {TARGET_MODULE} پیدا نشد"})
        return None, details
    details["status"] = "factory-loaded"
    return factory, details


def _extract_order(app: Any) -> List[str]:
    order: List[str] = []
    middleware_items = getattr(app, "user_middleware", []) or []
    for item in middleware_items:
        cls = getattr(item, "cls", None)
        if cls is None:
            continue
        name = getattr(cls, "__name__", str(cls))
        order.append(name)
    return order


def probe_and_validate(force: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Validate that RateLimitMiddleware precedes IdempotencyMiddleware."""

    factory, details = _load_factory()
    if factory is None:
        return (not force), details

    try:
        app = factory()
    except Exception as exc:  # pragma: no cover - defensive
        details.update({"status": "factory-error", "message": f"اجرای create_app با خطا مواجه شد: {exc}"})
        return False, details

    order = _extract_order(app)
    details.update({"order": order})

    if not order:
        message = "هیچ middleware سفارشی‌ای روی app ثبت نشده است"
        details.update({"status": "order-empty", "message": message})
        return (not force), details

    try:
        rate_index = order.index(RATE_LIMIT_MIDDLEWARE)
    except ValueError:
        message = (
            f"❸ MW_ORDER_INVALID: Middleware {RATE_LIMIT_MIDDLEWARE} یافت نشد؛ ترتیب معتبر نیست"
        )
        details.update({"status": "rate-missing", "message": message})
        return False, details

    try:
        idem_index = order.index(IDEMPOTENCY_MIDDLEWARE)
    except ValueError:
        message = (
            f"❸ MW_ORDER_INVALID: Middleware {IDEMPOTENCY_MIDDLEWARE} یافت نشد؛ ترتیب معتبر نیست"
        )
        details.update({"status": "idempotency-missing", "message": message})
        return False, details

    if rate_index < idem_index:
        message = (
            "ترتیب middleware صحیح است؛ "
            f"{RATE_LIMIT_MIDDLEWARE} در موقعیت {rate_index} قبل از {IDEMPOTENCY_MIDDLEWARE} در موقعیت {idem_index} قرار دارد"
        )
        details.update({"status": "valid", "message": message})
        return True, details

    message = (
        "❸ MW_ORDER_INVALID: "
        "ترتیب middleware نامعتبر است؛ "
        f"{IDEMPOTENCY_MIDDLEWARE} در موقعیت {idem_index} قبل از {RATE_LIMIT_MIDDLEWARE} در موقعیت {rate_index} قرار گرفته است"
    )
    details.update({"status": "invalid-order", "message": message})
    return False, details
