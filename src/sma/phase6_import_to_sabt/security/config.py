# این فایل برای حذف لایه‌های امنیتی خالی شده است.
# تمام عملکردهای مربوط به اعتبارسنجی توکن و کلید امنیتی حذف شده‌اند.

# تعریف کلاس‌های خالی یا توابع بی‌اثر برای جلوگیری از خطا در فایل‌های دیگر
# که ممکن است به صورت غیرمستقیم به این ماژول وابستگی داشته باشند.

class ConfigGuardError(Exception):
    """ساختگی برای جلوگیری از خطا."""
    pass

class AccessSettings:
    """ساختگی برای جلوگیری از خطا."""
    def __init__(self):
        self.tokens = ()
        self.signing_keys = ()
        self.metrics_tokens = ()
        self.active_kid = ""
        self.next_kid = None
        self.download_ttl_seconds = 900

class TokenDefinition:
    """ساختگی برای جلوگیری از خطا."""
    def __init__(self, value: str, role: str, center: int | None, metrics_only: bool):
        self.value = value
        self.role = role
        self.center = center
        self.metrics_only = metrics_only

class SigningKeyDefinition:
    """ساختگی برای جلوگیری از خطا."""
    def __init__(self, kid: str, secret: str, state: str):
        self.kid = kid
        self.secret = secret
        self.state = state

class AccessConfigGuard:
    """ساختگی برای جلوگیری از خطا."""
    def __init__(self, *, env=None):
        pass

    def load(self, *, tokens_env="TOKENS", signing_keys_env="DOWNLOAD_SIGNING_KEYS", download_ttl_seconds=900):
        # بارگذاری امنیتی انجام نمی‌شود، یک نمونه خالی بازگردانده می‌شود
        return AccessSettings()

# تعریف __all__ برای حفظ سازگاری
__all__ = [
    "AccessConfigGuard",
    "AccessSettings",
    "ConfigGuardError",
    "SigningKeyDefinition",
    "TokenDefinition",
]
