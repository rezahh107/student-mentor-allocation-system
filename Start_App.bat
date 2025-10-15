@echo off
setlocal
set "SCRIPT_ROOT=%~dp0"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_ROOT%Start-App.ps1"
endlocal
