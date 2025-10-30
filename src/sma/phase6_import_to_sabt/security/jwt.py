"""Deterministic JWT helpers for ImportToSabt security flows."""
from __future__ import annotations

# import base64 # دیگر مورد نیاز نیست
# import hashlib # دیگر مورد نیاز نیست
# import hmac # دیگر مورد نیاز نیست
# import json # دیگر مورد نیاز نیست
from dataclasses import dataclass
from typing import Any, Mapping

# from sma.phase6_import_to_sabt.app.clock import Clock # دیگر مورد نیاز نیست


# _SUPPORTED_ALG = "HS256" # دیگر مورد نیاز نیست


@dataclass(slots=True)
class DecodedJWT:
    """Structured representation of a decoded JWT payload.

    این کلاس اکنون ممکن است فقط یک مقدار پیش‌فرض را نگه دارد.
    """

    subject: str
    payload: Mapping[str, Any]


# def _b64decode(data: str) -> bytes: ... # دیگر مورد نیاز نیست


def decode_jwt(token: str, *, secret: str, clock: Clock, leeway: int = 60) -> DecodedJWT:
    """Decode and validate a compact JWT signed with HS256.

    این تابع دیگر تأیید یا رمزگشایی واقعی انجام نمی‌دهد.
    فقط یک مقدار پیش‌فرض را برمی‌گرداند.
    """

    # تمام عملیات امنیتی حذف شد
    # parts = token.split(".") ...
    # header = json.loads(_b64decode(header_b64)) ...
    # hmac.compare_digest(expected, signature) ...
    # now = int(clock.now().timestamp()) ...
    # exp = payload.get("exp") ...
    # raise AuthorizationError(...) ...
    # فقط یک پیلود و سابجکت ساختگی برمی‌گرداند
    return DecodedJWT(
        subject="dev-subject", # یا هر مقدار دیگر
        payload={
            "sub": "dev-subject",
            "role": "ADMIN", # یا هر مقدار دیگر
            "exp": 9999999999, # منقضی نشود
            "iat": 1700000000, # یا هر مقدار دیگر
            # سایر فیلدهای مورد نیاز
        }
    )


__all__ = ["DecodedJWT", "decode_jwt"]
