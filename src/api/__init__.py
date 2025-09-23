"""
ماژول API برای لایه کلاینت سیستم تخصیص منتور.

این پکیج شامل:
- مدل‌های DTO
- پیکربندی کلاینت
- استثناهای دامنه
- داده‌های Mock
- کلاس `APIClient` با پشتیبانی از Mock/Real
"""

from .config import APIConfig
from .exceptions import (
    APIException,
    NetworkException,
    ValidationException,
    BusinessRuleException,
)
from .models import (
    StudentDTO,
    MentorDTO,
    AllocationDTO,
    DashboardStatsDTO,
)
from .client import APIClient

__all__ = [
    "APIClient",
    "APIConfig",
    "APIException",
    "NetworkException",
    "ValidationException",
    "BusinessRuleException",
    "StudentDTO",
    "MentorDTO",
    "AllocationDTO",
    "DashboardStatsDTO",
]

