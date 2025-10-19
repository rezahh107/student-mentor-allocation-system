# Repo Doctor

ابزار «Repo Doctor» برای تمیزکاری و پایش مخازن Python با ساختار `src/` طراحی شده است.
این ابزار با محوریت سیستم‌عامل ویندوز، اطمینان می‌دهد که مشکلات واردات ماژول،
وابستگی‌های زمان اجرا، و سلامت سرویس FastAPI به صورت قطعی و قابل تکرار بررسی شوند.

## اجرای سریع (PowerShell 7)

```powershell
python -m venv .venv
. .venv\\Scripts\\Activate.ps1
pip install -r requirements-dev.txt
python tools/repo_doctor.py all --apply
```

## دستورات

| دستور | شرح |
|-------|------|
| `python tools/repo_doctor.py scan` | بررسی ناسازگاری واردات و تولید گزارش بدون تغییر | 
| `python tools/repo_doctor.py fix --apply` | اعمال اصلاح واردات، ایجاد `__init__.py`، تولید `.env` | 
| `python tools/repo_doctor.py deps --apply` | ساخت `requirements.runtime.txt` سازگار با Python 3.11/3.13 | 
| `python tools/repo_doctor.py health --apply` | اجرای سلامت‌سنج FastAPI/Uvicorn بدون اتصال شبکه | 
| `python tools/repo_doctor.py all --apply` | اجرای کامل تمام گام‌ها | 

## خطاهای کاربری (فارسی و قطعی)

- «مسیر فقط خواندنی است؛ لطفاً سطح دسترسی را بررسی کنید.»
- «ترتیب میان‌افزار نامعتبر است؛ باید RateLimit → Idempotency → Auth باشد.»
- «واردات ماژول نامعتبر است؛ پیشوند `src.` الزامی است.»

تمام نوشتارهای فایل به صورت اتمیک (`.part` → `fsync` → `rename`) و با پایان خط CRLF انجام می‌شود.
گزارش‌ها در پوشه `reports/` ایجاد شده و شامل لاگ JSON (NDJSON) و متریک‌های Prometheus هستند.
