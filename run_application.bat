@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
set "PYTHON_BIN="
set "HOST=0.0.0.0"
set "PORT=8000"
set "WORKERS=1"
if not "%APP_HOST%"=="" set "HOST=%APP_HOST%"
if not "%APP_PORT%"=="" set "PORT=%APP_PORT%"
if not "%APP_WORKERS%"=="" set "WORKERS=%APP_WORKERS%"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if exist "%VENV_PY%" set "PYTHON_BIN=%VENV_PY%"
if not defined PYTHON_BIN set "VENV_PY=%SCRIPT_DIR%.venv/bin/python"
if not defined PYTHON_BIN if exist "%VENV_PY%" set "PYTHON_BIN=%VENV_PY%"
if not defined PYTHON_BIN set "PYTHON_BIN=py"
"%PYTHON_BIN%" -V >nul 2>&1
if errorlevel 1 set "PYTHON_BIN=python"
"%PYTHON_BIN%" -V >nul 2>&1
if errorlevel 1 (
    echo ❌ پایتون در دسترس نیست.
    popd >nul
    exit /b 1
)
"%PYTHON_BIN%" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ❌ نسخهٔ پایتون باید ۳٫۸ یا بالاتر باشد.
    popd >nul
    exit /b 1
)
"%PYTHON_BIN%" -m pip show uvicorn >nul 2>&1
if errorlevel 1 (
    echo ❌ کتابخانهٔ uvicorn نصب نیست؛ ابتدا install_requirements.bat را اجرا کنید.
    popd >nul
    exit /b 1
)
if not exist "%SCRIPT_DIR%src\main.py" (
    echo ❌ فایل src\main.py یافت نشد.
    popd >nul
    exit /b 1
)
echo 🚀 اجرای برنامه با uvicorn...
"%PYTHON_BIN%" -m uvicorn src.main:app --host %HOST% --port %PORT% --workers %WORKERS%
if errorlevel 1 (
    echo ❌ اجرای سرور با خطا مواجه شد؛ فایل لاگ‌ها و تنظیمات را بررسی کنید.
    popd >nul
    exit /b 1
)
echo ✅ سرور با موفقیت متوقف شد.
popd >nul
exit /b 0
