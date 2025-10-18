@echo off
chcp 65001 >nul
title نصب کتابخانه‌ها
color 0A
cd /d "%~dp0"

echo ╔════════════════════════════════════════════════╗
echo ║     نصب کتابخانه‌های مورد نیاز                ║
echo ╚════════════════════════════════════════════════╝
echo.

echo 🌐 بررسی اتصال اینترنت...
ping -n 1 pypi.org >nul 2>&1
if errorlevel 1 (
    echo ⚠️ هشدار: اتصال به pypi.org برقرار نیست
    echo    نصب ممکن است با خطا مواجه شود
    timeout /t 3 >nul
)

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ خطا: پایتون نصب نیست!
    echo.
    echo 💡 راهنما:
    echo    1. از https://www.python.org/downloads/ آخرین نسخه را دانلود کنید
    echo    2. هنگام نصب تیک "Add Python to PATH" را بزنید
    echo    3. این فایل را دوباره اجرا کنید
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYVER=%%i
echo ✅ پایتون شناسایی شد: %PYVER%
echo.

REM Python version check (>=3.11)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ⚠️ هشدار: نسخه پایتون شما پایین‌تر از 3.11 است
    echo    برای عملکرد بهتر، پایتون 3.11+ توصیه می‌شود
    choice /C YN /M "آیا می‌خواهید با همین نسخه ادامه دهید؟ (Y/N)"
    if errorlevel 2 exit /b 1
)

REM Quick presence check (fastapi sentinel)
python -c "import fastapi" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo ⚠️ به نظر می‌رسد کتابخانه‌ها قبلاً نصب شده‌اند.
    echo.
    choice /C YN /M "آیا می‌خواهید دوباره نصب کنید (برای به‌روزرسانی)؟ (Y/N)"
    if errorlevel 2 (
        echo.
        echo ✅ نصب لغو شد. از کتابخانه‌های موجود استفاده می‌شود.
        timeout /t 2 >nul
        exit /b 0
    )
)

echo.
echo ═══════════════════════════════════════════════════
echo 📦 شروع نصب کتابخانه‌ها...
echo ═══════════════════════════════════════════════════
echo.

echo [1/3] به‌روزرسانی pip...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo ❌ خطا در به‌روزرسانی pip
    echo 💡 ممکن است نیاز به اجرای این فایل با "Run as Administrator" باشد
    pause
    exit /b 1
)
echo ✅ pip به‌روز شد

echo.
echo [2/3] نصب wheel و setuptools...
python -m pip install --upgrade wheel setuptools --quiet
echo ✅ ابزارهای نصب آماده شدند

echo.
echo [3/3] نصب کتابخانه‌های پروژه...
echo ⏱️ این مرحله ممکن است ۳-۵ دقیقه طول بکشد
echo.

pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ═══════════════════════════════════════════════════
    echo ❌ خطا در نصب کتابخانه‌ها
    echo ═══════════════════════════════════════════════════
    echo.
    echo 💡 راه‌حل‌های ممکن:
    echo    1. اتصال اینترنت را بررسی کنید
    echo    2. فایل requirements.txt را بررسی کنید
    echo    3. این فایل را با "Run as Administrator" اجرا کنید
    echo    4. فایل check_progress.py را برای جزئیات بیشتر اجرا کنید
    echo    5. دستور زیر را دستی در CMD اجرا کنید:
    echo       pip install -r requirements.txt --verbose
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════════════════╗
echo ║  ✅ نصب با موفقیت کامل شد!                    ║
echo ╚════════════════════════════════════════════════╝
echo.
echo 🎯 مرحله بعدی:
echo    1. فایل check_progress.py را اجرا کنید (برای تأیید)
echo    2. فایل run_application.bat را اجرا کنید
echo.
timeout /t 5 >nul
