@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul
set "PYTHON_BIN="
set "REQUIREMENTS_FILE=%SCRIPT_DIR%requirements.txt"
if not exist "%REQUIREMENTS_FILE%" (
    echo ❌ فایل الزامی یافت نشد: requirements.txt
    popd >nul
    exit /b 1
)
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if exist "%VENV_PY%" set "PYTHON_BIN=%VENV_PY%"
if not defined PYTHON_BIN set "VENV_PY=%SCRIPT_DIR%.venv/bin/python"
if not defined PYTHON_BIN if exist "%VENV_PY%" set "PYTHON_BIN=%VENV_PY%"
if not defined PYTHON_BIN set "PYTHON_BIN=py"
"%PYTHON_BIN%" -V >nul 2>&1
if errorlevel 1 set "PYTHON_BIN=python"
"%PYTHON_BIN%" -V >nul 2>&1
if errorlevel 1 (
    echo ❌ نسخهٔ پایتون شناسایی نشد یا کمتر از ۳٫۸ است.
    popd >nul
    exit /b 1
)
for /f "tokens=2 delims= " %%i in ('"%PYTHON_BIN%" -V 2^>nul') do set "PY_VERSION=%%i"
"%PYTHON_BIN%" -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ❌ نسخهٔ پایتون شناسایی نشد یا کمتر از ۳٫۸ است.
    popd >nul
    exit /b 1
)
echo ✅ پایتون %PY_VERSION% تایید شد.
"%PYTHON_BIN%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ ماژول pip در دسترس نیست.
    popd >nul
    exit /b 1
)
echo 🔁 در حال به‌روزرسانی pip...
"%PYTHON_BIN%" -m pip install --upgrade pip >nul
if errorlevel 1 (
    echo ❌ خطا در به‌روزرسانی pip.
    popd >nul
    exit /b 1
)
set "CONSTRAINT_ARGS="
for %%f in (constraints*.txt) do (
    if exist "%%~ff" call :APPEND_CONSTRAINT "%%~ff"
)
echo 📦 نصب وابستگی‌ها بر اساس requirements.txt...
"%PYTHON_BIN%" -m pip install --requirement "%REQUIREMENTS_FILE%"!CONSTRAINT_ARGS!
if errorlevel 1 (
    echo ❌ نصب کتابخانه‌ها با خطا روبه‌رو شد.
    popd >nul
    exit /b 1
)
echo ✅ همهٔ وابستگی‌ها با موفقیت نصب شدند.
popd >nul
exit /b 0
:APPEND_CONSTRAINT
set "CONSTRAINT_ARGS=%CONSTRAINT_ARGS% -c ""%~1"""
exit /b 0
