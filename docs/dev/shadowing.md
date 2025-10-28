# جلوگیری از سایه‌زنی بسته‌ها

برای پایبندی به «AGENTS.md::8 Testing & CI Gates» و حفظ قطعیت ایمپورت‌ها:

1. محیط محلی یا CI را با نصب ویرایشی راه‌اندازی کنید:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```
2. در صورت دریافت کد قدیمی، اسکریپت مهاجرت را اجرا کنید تا پوشه‌های first-party به `src/sma/` منتقل شوند:
   ```bash
   tools/migrate_shadowing.sh
   ```
3. سپس بازنویسی ایمپورت‌ها را انجام دهید:
   ```bash
   tools/rewrite_imports.py
   ```
4. از تنظیم `PYTHONPATH` با `src/` خودداری کنید. برای اطمینان، اسکریپت زیر قبل از کامیت اجرا می‌شود:
   ```bash
   python scripts/check_no_shadowing.py
   ```
5. برای تأیید، تست‌های نگهبان را اجرا کنید:
   ```bash
   pytest -q tests/imports
   ```

اگر اخطاری مشابه «خطا: قانون ایمپورت نقض شد؛ فقط از sma.* برای کد first-party استفاده کنید.» مشاهده کردید، مسیر ذکر شده را تصحیح کنید و مجدد تست‌ها را اجرا نمایید.
