@echo off
setlocal
if exist build rd /s /q build
if exist dist rd /s /q dist
pyinstaller -y -n StudentMentorApp --console ^
  --collect-data tzdata ^
  --hidden-import tenacity --collect-submodules tenacity ^
  --hidden-import windows_service.controller ^
  --collect-all phase6_import_to_sabt ^
  --collect-all windows_service ^
  --collect-all audit ^
  --collect-all ui ^
  --collect-all web ^
  --collect-all windows_shared ^
  windows_launcher\launcher.py
echo Build finished: dist\StudentMentorApp\StudentMentorApp.exe
endlocal
