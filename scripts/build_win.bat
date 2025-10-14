@echo off
setlocal
if exist build rd /s /q build
if exist dist rd /s /q dist

set "EXTRA_ARGS="
if exist windows_service\StudentMentorService.xml (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"windows_service\StudentMentorService.xml;windows_service\""
)
if exist src\ui (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"src\ui;ui\""
)
if exist src\web (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"src\web;web\""
)
if exist windows_shared (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"windows_shared;windows_shared\""
)
if exist src\audit (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"src\audit;audit\""
)
if exist src\phase6_import_to_sabt (
  set "EXTRA_ARGS=%EXTRA_ARGS% --add-data \"src\phase6_import_to_sabt;phase6_import_to_sabt\""
)

if defined EXTRA_ARGS (
  pyinstaller -y -n StudentMentorApp --console ^
    --collect-data tzdata ^
    --hidden-import tenacity --collect-submodules tenacity ^
    --hidden-import windows_service.controller --collect-submodules windows_service ^
    %EXTRA_ARGS% ^
    windows_launcher\launcher.py %*
) else (
  pyinstaller -y -n StudentMentorApp --console ^
    --collect-data tzdata ^
    --hidden-import tenacity --collect-submodules tenacity ^
    --hidden-import windows_service.controller --collect-submodules windows_service ^
    windows_launcher\launcher.py %*
)
echo Build finished: dist\StudentMentorApp\StudentMentorApp.exe
endlocal
