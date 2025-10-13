@echo off
setlocal
if exist build rd /s /q build
if exist dist rd /s /q dist
pyinstaller -y -n StudentMentorApp --console ^
  --collect-data tzdata ^
  --hidden-import tenacity --collect-submodules tenacity ^
  windows_launcher\launcher.py
echo Build finished: dist\StudentMentorApp\StudentMentorApp.exe
endlocal
