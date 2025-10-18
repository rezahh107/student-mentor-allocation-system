@echo off
chcp 65001 >nul
title اجرای برنامه - Student Mentor Allocation
color 0B
cd /d "%~dp0"

echo ╔════════════════════════════════════════════════╗
echo ║     اجرای برنامه (FastAPI + Uvicorn)          ║
echo ╚════════════════════════════════════════════════╝
echo.

REM پیش‌نیازسنجی کامل
echo 🔍 بررسی پیش‌نیازها...
echo.

REM 1. Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ پایتون یافت نشد
    echo 💡 لطفاً فایل check_progress.py را اجرا کنید
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo ✅ پایتون: %%i

REM 2. Core modules
echo ✅ بررسی کتابخانه‌های کلیدی...
python -c "import sys; [__import__(m) for m in ['fastapi','uvicorn','sqlalchemy','prometheus_client','pandas','openpyxl']]" >nul 2>&1
if errorlevel 1 (
    echo ❌ برخی کتابخانه‌های کلیدی نصب نیستند
    echo 💡 فایل install_requirements.bat را اجرا کنید
    pause
    exit /b 1
)
echo ✅ کتابخانه‌ها: OK

REM 3. Redis (optional but check)
python -c "import redis; r=redis.Redis(host='127.0.0.1',port=6379,socket_timeout=1); r.ping()" >nul 2>&1
if errorlevel 1 (
    python -c "import fakeredis" >nul 2>&1
    if not errorlevel 1 (
        echo ⚠️ Redis: استفاده از fakeredis (برای تست مناسب است)
    ) else (
        echo ⚠️ Redis: در دسترس نیست (برنامه با محدودیت اجرا می‌شود)
    )
) else (
    echo ✅ Redis: متصل به localhost:6379
)

REM 4. Main file
if not exist "src\phase2_uploads\app.py" (
    echo ❌ فایل اصلی برنامه یافت نشد: src\phase2_uploads\app.py
    echo 💡 مطمئن شوید در پوشه صحیح پروژه هستید
    pause
    exit /b 1
)
echo ✅ فایل‌های پروژه: OK

REM 5. Config
if not exist ".env" (
    if exist ".env.example" (
        echo ⚠️ فایل .env یافت نشد (از .env.example استفاده می‌شود)
    ) else (
        echo ⚠️ فایل .env یافت نشد (تنظیمات پیش‌فرض اعمال می‌شود)
    )
) else (
    echo ✅ پیکربندی: OK
)

echo.
echo ═══════════════════════════════════════════════════
echo 🚀 شروع سرور...
echo ═══════════════════════════════════════════════════
echo.
echo 📍 آدرس: http://127.0.0.1:8000
echo 📍 مستندات API: http://127.0.0.1:8000/docs
echo 📍 متریک‌ها: http://127.0.0.1:8000/metrics
echo.
echo ⚠️ برای توقف سرور: Ctrl+C
echo.
echo ═══════════════════════════════════════════════════

python -m uvicorn src.phase2_uploads.app:create_app --host 127.0.0.1 --port 8000 --log-level info

if errorlevel 1 (
    echo.
    echo ═══════════════════════════════════════════════════
    echo ❌ برنامه با خطا متوقف شد
    echo ═══════════════════════════════════════════════════
    echo.
    echo 💡 راهنمای عیب‌یابی:
    echo.
    echo    خطای "Port already in use":
    echo    ➜ پورت 8000 مشغول است
    echo    ➜ راه‌حل 1: این فایل را ویرایش کنید و --port 8000 را به --port 8080 تغییر دهید
    echo    ➜ راه‌حل 2: برنامه‌ای که پورت 8000 را اشغال کرده، ببندید
    echo.
    echo    خطای "ModuleNotFoundError":
    echo    ➜ فایل install_requirements.bat را دوباره اجرا کنید
    echo.
    echo    خطای دیگر:
    echo    ➜ فایل check_progress.py را اجرا کنید
    echo    ➜ متن کامل خطا را یادداشت کنید
    echo.
) else (
    echo.
    echo ═══════════════════════════════════════════════════
    echo ✅ سرور به درستی متوقف شد
    echo ═══════════════════════════════════════════════════
)

echo.
pause
