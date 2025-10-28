@echo off

setlocal enabledelayedexpansion

chcp 65001 >nul 2>&1



REM --- Determine Python (prefer venv) ---

set "PYTHON_BIN="

if exist ".venv\Scripts\python.exe" (

  set "PYTHON_BIN=.venv\Scripts\python.exe"

) else if exist ".venv/bin/python" (

  set "PYTHON_BIN=.venv/bin/python"

) else (

  where py >nul 2>&1 && set "PYTHON_BIN=py"

  if "%PYTHON_BIN%"=="" (

    where python >nul 2>&1 && set "PYTHON_BIN=python"

  )

)



if "%PYTHON_BIN%"=="" (

  echo ❌ Python 3.11 not found. Please install it (winget install Python.Python.3.11).

  exit /b 1

)



REM --- Defaults (overridable via env) ---

if "%APP_HOST%"=="" set "APP_HOST=0.0.0.0"

if "%APP_PORT%"=="" set "APP_PORT=8000"

if "%APP_WORKERS%"=="" set "APP_WORKERS=1"



REM --- Validate entrypoint ---

if not exist "main.py" (

  echo ❌ main.py not found at repo root. Expected entrypoint: main:app

  exit /b 1

)



echo 🚀 Starting FastAPI: main:app

echo    Host: %APP_HOST%  Port: %APP_PORT%  Workers: %APP_WORKERS%



"%PYTHON_BIN%" -m uvicorn main:app --host %APP_HOST% --port %APP_PORT% --workers %APP_WORKERS%

exit /b %ERRORLEVEL%

