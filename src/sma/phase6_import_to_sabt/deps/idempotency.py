"""Idempotency header validation helpers."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header, HTTPException

# _ZW_RE = re.compile(r"[\u200B-\u200D\uFEFF]") # حذف شد، دیگر مورد نیاز نیست

def require_idempotency_key(
    # idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None # حذف شد
) -> str:
    """Validate the Idempotency-Key header for POST job requests.

    این تابع دیگر اعتبارسنجی انجام نمی‌دهد.
    فقط یک کلید پیش‌فرض برمی‌گرداند.
    """
    # تمام اعتبارسنجی‌ها حذف شد
    # if idempotency_key is None: ...
    # key = _ZW_RE.sub("", idempotency_key).strip() ...
    # if not key: ...
    # if len(key) > 128: ...
    # فقط یک کلید ساده برمی‌گرداند
    return "dev-idempotency-key" # یا هر مقدار پیش‌فرض دیگر

# اگر می‌خواهیم همچنان Header را دریافت کنیم اما اعتبارسنجی نکنیم:
# def require_idempotency_key(
#     idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None
# ) -> str:
#     """Validate the Idempotency-Key header for POST job requests.
#
#     این تابع دیگر اعتبارسنجی انجام نمی‌دهد.
#     فقط مقدار ورودی یا یک مقدار پیش‌فرض را برمی‌گرداند.
#     """
#     # تمام اعتبارسنجی‌ها حذف شد
#     # فقط مقدار ورودی یا یک مقدار پیش‌فرض برمی‌گرداند
#     return idempotency_key or "dev-idempotency-key"
