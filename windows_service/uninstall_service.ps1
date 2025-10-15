Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-WindowsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw 'اجرای این اسکریپت نیازمند دسترسی Administrator است.'
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$winswExecutable = Join-Path -Path $scriptRoot -ChildPath 'StudentMentorService.exe'

Assert-WindowsAdministrator

if (-not (Test-Path -Path $winswExecutable)) {
    Write-Warning "فایل StudentMentorService.exe در مسیر $winswExecutable موجود نیست؛ سرویس احتمالاً از قبل حذف شده است."
    exit 0
}

Push-Location -Path $scriptRoot
try {
    & $winswExecutable stop | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'توقف سرویس ممکن نشد یا سرویس در حال اجرا نبود.'
    }

    & $winswExecutable uninstall | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'حذف سرویس ناموفق بود.'
    }

    Write-Host '🗑️  سرویس StudentMentorService حذف شد.'
}
finally {
    Pop-Location
}
