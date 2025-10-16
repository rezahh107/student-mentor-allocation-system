Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('create', 'delete', 'run')]
    [string]$Action,
    [string]$TaskName = 'SMASM_AutoStart'
)

function Assert-WindowsPlatform {
    $platform = [System.Environment]::OSVersion.Platform
    if ($platform -ne 'Win32NT' -and $platform -ne 2) {
        throw 'این اسکریپت فقط روی Windows قابل اجرا است.'
    }
}

function Invoke-Schtasks {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $process = Start-Process -FilePath 'schtasks.exe' -ArgumentList $Arguments -Wait -NoNewWindow -PassThru
    if ($process.ExitCode -ne 0) {
        throw "فرمان schtasks ناموفق بود (ExitCode=$($process.ExitCode))."
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -Path (Join-Path $scriptRoot '..')).Path
$startAppPath = Join-Path -Path $repoRoot -ChildPath 'Start-App.ps1'

if (-not (Test-Path -Path $startAppPath)) {
    throw "Start-App.ps1 در مسیر $startAppPath پیدا نشد."
}

Assert-WindowsPlatform

switch ($Action) {
    'create' {
        $escapedCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$startAppPath`""
        Invoke-Schtasks -Arguments @(
            '/Create',
            '/TN', $TaskName,
            '/SC', 'ONLOGON',
            '/RL', 'HIGHEST',
            '/F',
            '/TR', $escapedCommand
        )
        Write-Host "✅ وظیفه زمان‌بندی‌شده $TaskName ایجاد شد."
    }
    'delete' {
        Invoke-Schtasks -Arguments @(
            '/Delete',
            '/TN', $TaskName,
            '/F'
        )
        Write-Host "🗑️  وظیفه زمان‌بندی‌شده $TaskName حذف شد."
    }
    'run' {
        Invoke-Schtasks -Arguments @(
            '/Run',
            '/TN', $TaskName
        )
        Write-Host "🚀 وظیفه زمان‌بندی‌شده $TaskName اجرا شد."
    }
    default {
        throw "دستور ناشناخته: $Action"
    }
}
