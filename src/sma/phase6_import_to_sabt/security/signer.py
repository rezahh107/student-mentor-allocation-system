from __future__ import annotations

# import base64 # دیگر مورد نیاز نیست یا کمتر
# import hmac # دیگر مورد نیاز نیست
# import logging # دیگر مورد نیاز نیست
# import os # دیگر مورد نیاز نیست
from dataclasses import dataclass
# from datetime import datetime # دیگر مورد نیاز نیست
from typing import Iterable, Mapping, MutableMapping
# from urllib.parse import parse_qs, urlparse # دیگر مورد نیاز نیست

# from binascii import Error as Base64Error # دیگر مورد نیاز نیست

from sma.phase6_import_to_sabt.models import SignedURLProvider # این را قبلاً تغییر دادیم
# from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition # دیگر مورد نیاز نیست


# logger = logging.getLogger(__name__) # دیگر مورد نیاز نیست


# کلاس SignatureError دیگر عملکرد امنیتی ندارد
class SignatureError(Exception):
    """Raised when signed URL validation fails.

    این کلاس دیگر مورد استفاده قرار نمی‌گیرد، اما برای جلوگیری از خطا در فایل‌های دیگر ممکن است نگه داشته شود.
    """

    def __init__(self, message_fa: str, *, reason: str) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason


@dataclass(frozen=True)
class SignedURLComponents:
    # تغییر فیلدها برای سادگی بیشتر یا نگه داشتن ساختار قبلی
    # مثلاً فقط یک نام فایل ذخیره کنیم
    path: str
    # token_id: str # حذف شد یا تغییر کرد
    # kid: str # حذف شد یا تغییر کرد
    # expires: int # حذف شد یا تغییر کرد
    # signature: str # حذف شد یا تغییر کرد

    def as_query(self) -> Mapping[str, str]:
        # فقط یک پاسخ ساده یا خالی برمی‌گرداند
        return {}

    @property
    def signed(self) -> str:
        return self.path # یا مقدار دیگر

    @property
    def exp(self) -> int:
        return 9999999999 # منقضی نشود # تغییر داده شد

    @property
    def sig(self) -> str:
        return "dev-sig" # یا هر مقدار دیگر # تغییر داده شد


class SigningKeySet:
    """Store active and next signing keys for dual rotation.

    این کلاس دیگر کلیدهای واقعی را مدیریت نمی‌کند.
    فقط یک کلید ساختگی نگه می‌دارد.
    """

    def __init__(self, definitions: Iterable[SigningKeyDefinition]) -> None:
        # self._definitions: MutableMapping[str, SigningKeyDefinition] = {item.kid: item for item in definitions} # دیگر مورد نیاز نیست
        # فقط یک کلید ساختگی ایجاد می‌کنیم
        from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition # فقط برای اینجا
        fake_key = SigningKeyDefinition(kid="dev-kid", secret="dev-secret", state="active")
        self._definitions: MutableMapping[str, SigningKeyDefinition] = {fake_key.kid: fake_key}

    def active(self) -> SigningKeyDefinition:
        # فقط کلید ساختگی را برمی‌گرداند
        return list(self._definitions.values())[0] # تغییر داده شد

    def get(self, kid: str) -> SigningKeyDefinition | None:
        # فقط کلید ساختگی را برمی‌گرداند
        return self._definitions.get(kid) # تغییر داده شد

    def allowed_for_verification(self) -> set[str]:
        # فقط کلید ساختگی را مجاز می‌داند
        return set(self._definitions.keys()) # تغییر داده شد


class DualKeySigner(SignedURLProvider):
    """Generate and verify download URLs using dual rotating keys.

    این کلاس دیگر امضای واقعی تولید یا تأیید نمی‌کند.
    فقط مقادیر ساختگی یا ساده برمی‌گرداند.
    """

    def __init__(
        self,
        *,
        keys: SigningKeySet,
        clock,
        metrics,
        default_ttl_seconds: int,
        base_path: str = "/download",
    ) -> None:
        # self._keys = keys # دیگر ممکن است مورد نیاز نباشد
        # self._clock = clock # دیگر ممکن است مورد نیاز نباشد
        # self._metrics = metrics # دیگر ممکن است مورد نیاز نباشد
        # self._default_ttl = default_ttl_seconds # دیگر ممکن است مورد نیاز نباشد
        # self._base_path = base_path.rstrip("/") or "/download" # دیگر ممکن است مورد نیاز نباشد
        # self._debug = os.getenv("DEBUG_SIG") == "1" # دیگر ممکن است مورد نیاز نباشد
        pass # هیچ کاری نمی‌کند

    def issue(
        self,
        path: str,
        *,
        ttl_seconds: int | None = None,
        method: str = "GET",
        query: Mapping[str, str] | None = None,
    ) -> SignedURLComponents:
        # دیگر عملکرد امنیتی ندارد
        # normalized_path = self._normalize_path(path) ...
        # expires_at = int(self._clock.now().timestamp()) + max(1, int(expires_in)) ...
        # active = self._keys.active() ...
        # canonical = self._canonical(method, normalized_path, query or {}, expires_at) ...
        # signature = self._sign(active.secret, canonical) ...
        # self._metrics.download_signed_total.labels(outcome="issued").inc() ...
        # فقط یک شیء SignedURLComponents با مسیر ورودی یا ساختگی برمی‌گرداند
        return SignedURLComponents(path=path)

    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        """تابع تولید URL دیگر امضای واقعی ایجاد نمی‌کند."""
        # components = self.issue(file_path, ttl_seconds=expires_in) ...
        # فقط یک URL ساختگی یا مبتنی بر نام فایل برمی‌گرداند
        import os
        filename = os.path.basename(file_path)
        # این فقط یک نمونه است، می‌تواند به صورت دیگری نیز باشد
        return f"http://dev-server.local/files/{filename}"

    def verify_components(
        self,
        *,
        token_id: str | None = None,
        token: str | None = None,
        signed: str | None = None,
        kid: str | None = None,
        expires: int | None = None,
        exp: int | None = None,
        signature: str | None = None,
        sig: str | None = None,
        now: datetime | None = None,
    ) -> str:
        """تابع تأیید مؤلفه‌ها دیگر چک امنیتی انجام نمی‌دهد."""
        # تمام چک‌های امنیتی حذف شد
        # if token_value is None: ...
        # if not kid: ...
        # if expiry_value is None: ...
        # if signature_value is None: ...
        # try: path = self._decode_path(token_value) ...
        # now_ts = int((now or self._clock.now()).timestamp()) ...
        # if expiry_value <= now_ts: ...
        # if kid not in self._keys.allowed_for_verification(): ...
        # key = self._keys.get(kid) ...
        # canonical = self._canonical("GET", path, {}, expiry_value) ...
        # expected = self._sign(key.secret, canonical) ...
        # if not hmac.compare_digest(expected, signature_value): ...
        # self._metrics.download_signed_total.labels(outcome="ok").inc() ...
        # فقط مسیری که قبلاً ورودی گرفته یا یک مسیر پیش‌فرض را برمی‌گرداند
        # فرض می‌کنیم token_id همان مسیر رمزگذاری شده است
        import base64
        from binascii import Error as Base64Error
        token_value = token_id or token or signed
        if token_value is None:
             raise SignatureError("توکن نامعتبر است.", reason="missing_token")
        try:
            padding = "=" * (-len(token_value) % 4)
            raw = base64.urlsafe_b64decode(token_value + padding)
            path = raw.decode("utf-8")
        except (Base64Error, ValueError, UnicodeDecodeError) as exc:
            raise SignatureError("توکن نامعتبر است.", reason="token_decode") from exc
        return path # یا فقط یک مسیر ثابت مانند "verified/path"

    def verify(self, url: str, *, now: datetime | None = None) -> bool:
        """تابع تأیید URL دیگر چک امنیتی انجام نمی‌دهد."""
        # تمام چک‌ها حذف شد
        # parsed = urlparse(url) ...
        # query = parse_qs(parsed.query) ...
        # if not token_id or not kid or not expires_text or not sig: ...
        # try: expires = int(expires_text) ...
        # try: self.verify_components(...) ...
        # فقط True برمی‌گرداند
        return True # تغییر داده شد

    # توابع کمکی نیز باید تغییر یا حذف شوند
    # @staticmethod
    # def _normalize_path(path: str) -> str: ...
    # def _canonical(...) -> bytes: ...
    # @staticmethod
    # def _sign(secret: str, canonical: bytes) -> str: ...
    # @staticmethod
    # def _decode_path(value: str) -> str: ...

    # می‌توانیم فقط یک _normalize_path ساده نگه داریم یا کلاً حذف کنیم
    # اما verify_components از _decode_path استفاده می‌کند، پس باید آن را نیز تغییر دهیم
    # چون verify_components دیگر واقعاً تأیید نمی‌کند، _decode_path را می‌توان ساده کرد
    @staticmethod
    def _normalize_path(path: str) -> str:
        # فقط چک مسیر نامعتبر ساده
        if path.startswith("../") or "../" in path:
            raise SignatureError("توکن نامعتبر است.", reason="path_traversal")
        return path

    # @staticmethod
    # def _sign(secret: str, canonical: bytes) -> str: # دیگر مورد نیاز نیست

    @staticmethod
    def _decode_path(value: str) -> str:
        # این تابع همچنان ممکن است در verify_components استفاده شود، بنابراین باید باقی بماند یا تغییر کند
        # اما چون verify_components دیگر واقعاً چیزی رمزگشایی نمی‌کند، می‌توانیم آن را تغییر دهیم
        # اما برای اینکه سازگار باشد، یک نسخه ساده‌شده می‌سازیم
        import base64
        from binascii import Error as Base64Error
        padding = "=" * (-len(value) % 4)
        try:
            raw = base64.urlsafe_b64decode(value + padding)
        except (Base64Error, ValueError) as exc:
            raise SignatureError("توکن نامعتبر است.", reason="token_decode") from exc
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SignatureError("توکن نامعتبر است.", reason="token_decode") from exc
        return DualKeySigner._normalize_path(decoded)

    def _canonical(self, method: str, path: str, query: Mapping[str, str], exp: int) -> bytes:
        # دیگر مورد استفاده نیست
        return b""


__all__ = ["DualKeySigner", "SignatureError", "SignedURLComponents", "SigningKeySet"]
