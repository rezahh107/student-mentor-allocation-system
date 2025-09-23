# یادداشت‌های توسعه‌دهنده (Phase 2)

این سند نکات مهم برای تیم فاز ۲ (ادغام با Backend واقعی) را پوشش می‌دهد.

## ساختار پروژه
- معماری MVP برای UI
- لایه API Client با Mock/Real و Retry/Logging
- سرویس‌های Analytics، Report، Export، Realtime

## نقاط ادغام Backend
- `src/api/client.py`
  - `get_students(filters, date_range, pagination)` — پشتیبانی از `created_at__gte/lte`
  - `get_students_paginated(filters, date_range)` — انتظار `{students, total_count}`
  - CRUD دانش‌آموز (`create_student`, `update_student`, `delete_student`)
  - `get_dashboard_stats()` — بازگشت DTO آمار کلی
- احراز هویت و هدرها: در صورت نیاز اضافه شود.

## داده‌ها و DTOها
- StudentDTO ساختار واقعی (first/last/national_code/phone/...)
- تابع `migrate_student_dto` برای پشتیبانی سازگاری عقب‌رو

## فونت‌ها و بین‌المللی‌سازی
- فونت‌های فارسی در `assets/fonts/`
- در PDF از ReportLab + Vazir استفاده می‌شود.

## Realtime
- سرویس WebSocket اختیاری (پکیج `websockets`)
- Presenter داشبورد قابلیت فعال‌سازی دارد.

## تست‌ها
- تست‌های واحد پایه در `tests/`
- می‌توان سناریوهای Integration را به `docs/TESTING.md` افزود.

## نکات عملکرد
- AnalyticsService بر اساس `total_students` تصمیم می‌گیرد که فیلتر سمت سرور را اعمال کند یا خیر.
- برای دیتاست‌های بزرگ، توصیه می‌شود فیلتر تاریخ در Backend پیاده‌سازی و صفحه‌بندی واقعی استفاده شود.

