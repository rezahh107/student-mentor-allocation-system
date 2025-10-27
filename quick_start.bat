@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
goto :CHECK_PROGRESS
:CHECK_PROGRESS
python check_progress.py --json >nul 2>&1
if errorlevel 1 goto :NEED_INSTALL
goto :RUN_APP
:NEED_INSTALL
echo ⚠️ برخی پیش‌نیازها کامل نیست؛ نصب آغاز می‌شود.
call install_requirements.bat
if errorlevel 1 (
    echo ❌ نصب وابستگی‌ها ناموفق بود.
    popd >nul
    exit /b 1
)
python check_progress.py --json >nul 2>&1
if errorlevel 1 (
    echo ❌ پس از نصب نیز برخی خطاها باقی است؛ جزئیات را در check_progress.py ببینید.
    popd >nul
    exit /b 1
)
:RUN_APP
call run_application.bat
if errorlevel 1 (
    echo ❌ اجرای برنامه ناموفق بود.
    popd >nul
    exit /b 1
)
popd >nul
exit /b 0
