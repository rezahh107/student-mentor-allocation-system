# این فایل برای حذف لایه‌های امنیتی خالی شده است.
from __future__ import annotations

from collections.abc import Mapping

# تمام عملکردهای مربوط به اعتبارسنجی توکن و کلید امنیتی حذف شده‌اند.

# تعریف کلاس‌های خالی یا توابع بی‌اثر برای جلوگیری از خطا در فایل‌های دیگر
# که ممکن است به صورت غیرمستقیم به این ماژول وابستگی داشته باشند.

class ConfigGuardError(Exception):
    """ساختگی برای جلوگیری از خطا."""
    pass

class AccessSettings:
    """ساختگی برای جلوگیری از خطا."""

    def __init__(self) -> None:
        self.tokens: tuple[TokenDefinition, ...] = ()
        self.signing_keys: tuple[SigningKeyDefinition, ...] = ()
        self.metrics_tokens: tuple[TokenDefinition, ...] = ()
        self.active_kid: str = ""
        self.next_kid: str | None = None
        self.download_ttl_seconds: int = 900

class TokenDefinition:
    """ساختگی برای جلوگیری از خطا."""

    def __init__(self, value: str, role: str, center: int | None, metrics_only: bool) -> None:
        self.value: str = value
        self.role: str = role
        self.center: int | None = center
        self.metrics_only: bool = metrics_only

class SigningKeyDefinition:
    """ساختگی برای جلوگیری از خطا."""

    def __init__(self, kid: str, secret: str, state: str) -> None:
        self.kid: str = kid
        self.secret: str = secret
        self.state: str = state

class AccessConfigGuard:
    """ساختگی برای جلوگیری از خطا."""

    def __init__(self, *, env: Mapping[str, str] | None = None) -> None:
        self._env: Mapping[str, str] | None = env

    def load(
        self,
        *,
        tokens_env: str = "TOKENS",
        signing_keys_env: str = "DOWNLOAD_SIGNING_KEYS",
        download_ttl_seconds: int = 900,
    ) -> AccessSettings:
        """بارگذاری ساختگی که همواره تنظیمات خالی بازمی‌گرداند."""

        _ = (tokens_env, signing_keys_env, download_ttl_seconds, self._env)
        return AccessSettings()

# تعریف __all__ برای حفظ سازگاری
__all__ = [
    "AccessConfigGuard",
    "AccessSettings",
    "ConfigGuardError",
    "SigningKeyDefinition",
    "TokenDefinition",
]
