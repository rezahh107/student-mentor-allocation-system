from __future__ import annotations

# import hashlib # دیگر مورد نیاز نیست
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Sequence

# from sma.phase6_import_to_sabt.app.clock import Clock, build_system_clock # دیگر مورد نیاز نیست
# from sma.phase6_import_to_sabt.security.config import TokenDefinition # دیگر مورد نیاز نیست

# from .jwt import decode_jwt # دیگر مورد نیاز نیست


# کلاس AuthorizationError دیگر عملکرد امنیتی ندارد
class AuthorizationError(Exception):
    """Raised when RBAC rules reject the current request.

    این کلاس دیگر مورد استفاده قرار نمی‌گیرد، اما برای جلوگیری از خطا در فایل‌های دیگر ممکن است نگه داشته شود.
    """

    def __init__(self, message_fa: str, *, reason: str) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason


@dataclass(frozen=True)
class AuthenticatedActor:
    token_fingerprint: str
    role: Literal["ADMIN", "MANAGER", "METRICS_RO"]
    center_scope: int | None
    metrics_only: bool

    def can_access_center(self, center: int | None) -> bool:
        # دیگر چکی انجام نمی‌دهد، همیشه True برمی‌گرداند
        return True # تغییر داده شد


class TokenRegistry:
    """Token/JWT authenticator with deterministic hashing for observability.

    این کلاس دیگر تأیید واقعی انجام نمی‌دهد.
    فقط یک کاربر تأیید شده پیش‌فرض برمی‌گرداند.
    """

    def __init__(
        self,
        tokens: Sequence[TokenDefinition],
        *,
        hash_salt: str = "import-to-sabt",
        jwt_secret: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        # تمام متغیرهای قبلی دیگر مورد نیاز نیستند
        # self._records = {record.value: record for record in tokens}
        # self._metrics_tokens = {record.value for record in tokens if record.metrics_only}
        # self._hash_salt = hash_salt.encode("utf-8")
        # self._jwt_secret = jwt_secret
        # self._clock = clock or build_system_clock("Asia/Tehran")
        pass # هیچ کاری نمی‌کند

    def authenticate(self, value: str, *, allow_metrics: bool) -> AuthenticatedActor:
        """تابع احراز هویت دیگر عملکرد امنیتی ندارد."""
        # تمام چک‌ها و فراخوانی‌های decode_jwt حذف شد
        # if not value: ...
        # record = self._records.get(value) ...
        # if self._jwt_secret and "." in value: ...
        # decoded = decode_jwt(value, secret=self._jwt_secret, clock=self._clock) ...
        # raise AuthorizationError(...) ...
        # فقط یک کاربر ساختگی با مقادیر پیش‌فرض برمی‌گرداند
        return AuthenticatedActor(
            token_fingerprint="dev-fp", # یا هر مقدار دیگر
            role="ADMIN", # یا هر مقدار دیگر
            center_scope=999, # یا هر مقدار دیگر
            metrics_only=False, # یا هر مقدار دیگر
        )

    # سایر توابع نیز باید تغییر کنند یا حذف شوند
    def is_metrics_token(self, value: str) -> bool:
        # فقط یک مقدار پیش‌فرض برمی‌گرداند
        return False # یا True، بسته به نیاز # تغییر داده شد

    # def _actor_from_claims(self, payload: Mapping[str, object], *, token: str) -> AuthenticatedActor: ...
    # def _fingerprint(self, value: str) -> str: ...
    # def tokens(self) -> Iterable[str]: ...

    # می‌توان توابع دیگر را نیز ساده یا حذف کرد، اما برای سازگاری ممکن است نگه داشته شوند
    def _actor_from_claims(self, payload: Mapping[str, object], *, token: str) -> AuthenticatedActor:
        # فقط یک کاربر ساختگی برمی‌گرداند
        return AuthenticatedActor(
            token_fingerprint="dev-fp",
            role="ADMIN",
            center_scope=999,
            metrics_only=False,
        )

    def _fingerprint(self, value: str) -> str:
        # فقط یک اثر انگشت ساختگی برمی‌گرداند
        return "dev-fp" # تغییر داده شد

    def tokens(self) -> Iterable[str]:
        # فقط یک لیست ساختگی برمی‌گرداند
        return [] # تغییر داده شد


def enforce_center_scope(actor: AuthenticatedActor, *, center: int | None) -> None:
    """تابع بررسی محدوده دیگر چکی انجام نمی‌دهد."""
    # هیچ کاری نمی‌کند
    pass # تغییر داده شد


__all__ = [
    "AuthenticatedActor",
    "AuthorizationError",
    "TokenRegistry",
    "enforce_center_scope",
]
