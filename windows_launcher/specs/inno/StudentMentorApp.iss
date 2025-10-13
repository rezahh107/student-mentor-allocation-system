; Student Mentor Allocation installer (Inno Setup script)

#define AppName "Student Mentor Allocation"
#define AppVersion "1.0.0"
#define AppPublisher "ImportToSabt"
#define DefaultDirName "{autopf}\StudentMentorApp"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={#DefaultDirName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir="dist"
OutputBaseFilename="StudentMentorApp_Setup"
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source="..\dist\StudentMentorApp\StudentMentorApp.exe"; DestDir="{app}"; Flags: ignoreversion
Source="..\windows_service\StudentMentorService.xml"; DestDir="{app}\service"; Flags: ignoreversion
Source="..\windows_service\StudentMentorService.exe"; DestDir="{app}\service"; Flags: ignoreversion
; optional WebView2 bootstrapper must be placed alongside artifacts during packaging
Source="..\artifacts\MicrosoftEdgeWebview2Setup.exe"; DestDir="{tmp}"; Flags: deleteafterinstall skipifdoesntexist

[Icons]
Name="{autoprograms}\Student Mentor Allocation"; Filename="{app}\StudentMentorApp.exe"
Name="{autodesktop}\Student Mentor Allocation"; Filename="{app}\StudentMentorApp.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "ایجاد میانبر روی دسکتاپ"; GroupDescription: "میانبرها:"

[Run]
Filename="{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters="/install /silent"; StatusMsg="در حال نصب WebView2…"; Flags: skipifdoesntexist runhidden
Filename="{app}\service\StudentMentorService.exe"; Parameters="install"; StatusMsg="راه‌اندازی سرویس پس‌زمینه…"; Flags: runhidden postinstall skipifdoesntexist

[UninstallRun]
Filename="{app}\service\StudentMentorService.exe"; Parameters="uninstall"; Flags: runhidden skipifdoesntexist
