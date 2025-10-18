@echo off
chcp 65001 >nul
title راه‌انداز سریع - Quick Start
color 0E
cd /d "%~dp0"

echo ╔════════════════════════════════════════════════╗
echo ║          راه‌انداز سریع پروژه                  ║
echo ╚════════════════════════════════════════════════╝
echo.
echo این اسکریپت به‌صورت خودکار:
echo   1. وضعیت سیستم را بررسی می‌کند
echo   2. در صورت نیاز، کتابخانه‌ها را نصب می‌کند
echo   3. برنامه را اجرا می‌کند
echo.
pause

echo.
echo [1/3] بررسی وضعیت...
python check_progress.py
if errorlevel 1 (
    echo.
    echo ⚠️ برخی پیش‌نیازها ناقص هستند
    choice /C YN /M "آیا می‌خواهید نصب خودکار انجام شود؟ (Y/N)"
    if errorlevel 2 exit /b 1

    echo.
    echo [2/3] نصب کتابخانه‌ها...
    call install_requirements.bat
    if errorlevel 1 (
        echo ❌ نصب با خطا مواجه شد
        pause
        exit /b 1
    )
)

echo.
echo [3/3] اجرای برنامه...
timeout /t 2 >nul
call run_application.bat
