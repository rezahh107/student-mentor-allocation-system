class APIException(Exception):
    """استثنای پایه برای خطاهای لایه API."""


class NetworkException(APIException):
    """خطاهای ارتباط شبکه و عدم دسترسی به سرویس."""


class ValidationException(APIException):
    """خطاهای اعتبارسنجی ورودی یا پاسخ (۴۰۰-سری)."""


class BusinessRuleException(APIException):
    """نقض قوانین کسب‌وکار (مثلاً ظرفیت یا عدم تطابق قوانین تخصیص)."""

