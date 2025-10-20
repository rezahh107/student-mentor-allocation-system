# چک‌لیست راه‌اندازی ویندوز (PowerShell 7)

این چک‌لیست برای توسعه‌دهندگانی است که از PowerShell 7.4+ و Python 3.11 x64 استفاده می‌کنند. تمام گام‌ها فقط خواندنی بوده و مطابق خط‌مشی مخزن پیام‌های فارسی قطعی تولید می‌کنند.

## مراحل ضروری
- [ ] ایجاد و فعال‌سازی محیط مجازی:
  ```powershell
  py -3.11 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- [ ] به‌روزرسانی ابزارهای ساخت و نصب editable (شامل وابستگی‌های dev):
  ```powershell
  python -m pip install -U pip setuptools wheel
  pip install -e .[dev]
  ```
- [ ] اجرای نگهبان‌های مخزن:
  ```powershell
  python scripts/verify_agents.py
  python scripts/guard_pythonpath.py
  ```
- [ ] اجرای اسکریپت راه‌اندازی سرویس:
  ```powershell
  pwsh -File .\Start-App.ps1
  ```
- [ ] اجرای اسموک‌تست و مشاهدهٔ خروجی‌های اصلی:
  ```powershell
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q `
    tests/scripts/test_pythonpath_guard.py `
    tests/windows_service/test_start_app_script.py
  Get-Content .\logs\app-stdout.log -Wait
  ```
- [ ] بررسی متریک‌ها و اسکریپت تشخیصی:
  ```powershell
  pwsh -File .\win-dev-setup.ps1 -Base 'http://127.0.0.1:25119'
  pwsh -File .\tools\win\diagnose.ps1
  ```

## Common Errors (خطاهای متداول)
> «پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.» — فرمان `python scripts/verify_agents.py` این پیام را در صورت حذف یا جابه‌جایی فایل AGENTS صادر می‌کند.

## منابع تکمیلی
- مستند کامل: [docs/windows-powershell-setup.md](./windows-powershell-setup.md)
- اسکریپت تشخیصی: [tools/win/diagnose.ps1](../tools/win/diagnose.ps1)
