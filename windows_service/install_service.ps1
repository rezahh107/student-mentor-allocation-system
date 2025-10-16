Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

[CmdletBinding()]
param(
    [Parameter()][ValidateSet('install', 'start', 'stop', 'restart', 'status')]
    [string]$Action = 'install',
    [string]$WinSWVersion = '3.0.2'
)

function Assert-WindowsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw 'اجرای این اسکریپت نیازمند دسترسی Administrator است.'
    }
}

function Ensure-WinSW {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$Version
    )

    if (Test-Path -Path $ExecutablePath) {
        return
    }

    $downloadUrl = "https://github.com/winsw/winsw/releases/download/v$Version/WinSW-x64.exe"
    $tempFile = Join-Path -Path ([IO.Path]::GetDirectoryName($ExecutablePath)) -ChildPath "WinSW-x64-$Version.exe"

    Write-Host "⬇️  در حال دانلود WinSW $Version از $downloadUrl" -ForegroundColor Yellow
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tempFile
    Move-Item -Path $tempFile -Destination $ExecutablePath -Force
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -Path (Join-Path $scriptRoot '..')).Path
$executableName = 'StudentMentorService.exe'
$winswExecutable = Join-Path -Path $scriptRoot -ChildPath $executableName
$configPath = Join-Path -Path $scriptRoot -ChildPath 'StudentMentorService.xml'

if (-not (Test-Path -Path $configPath)) {
    throw "فایل تنظیمات WinSW در مسیر $configPath پیدا نشد."
}

Assert-WindowsAdministrator
Ensure-WinSW -ExecutablePath $winswExecutable -Version $WinSWVersion

function Invoke-WinSW {
    param(
        [Parameter(Mandatory = $true)][string]$Command
    )

    Push-Location -Path $scriptRoot
    try {
        $output = & $winswExecutable $Command
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $message = if ($output) { $output } else { "ExitCode=$exitCode" }
            throw "WinSW فرمان '$Command' ناموفق بود: $message"
        }
        if ($output) {
            Write-Host $output
        }
    }
    finally {
        Pop-Location
    }
}

switch ($Action) {
    'install' {
        Invoke-WinSW -Command 'install'
        Write-Host '✅ سرویس نصب شد.'
        Invoke-WinSW -Command 'start'
        Write-Host '🚀 سرویس راه‌اندازی شد.'
    }
    'start' {
        Invoke-WinSW -Command 'start'
        Write-Host '🚀 سرویس راه‌اندازی شد.'
    }
    'stop' {
        Invoke-WinSW -Command 'stop'
        Write-Host '⏹️  سرویس متوقف شد.'
    }
    'restart' {
        Invoke-WinSW -Command 'restart'
        Write-Host '🔁 سرویس بازنشانی شد.'
    }
    'status' {
        Invoke-WinSW -Command 'status'
    }
    default {
        throw "دستور ناشناخته: $Action"
    }
}
