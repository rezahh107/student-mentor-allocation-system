[CmdletBinding()]
param(
    [int[]]$CheckPorts = @(8000, 5432, 6379)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Invoke-Failure {
    param([Parameter(Mandatory)][string]$Message)
    Write-Error $Message
    throw $Message
}

function Test-PortFree {
    param([Parameter(Mandatory)][int]$Port,[string]$Host = '127.0.0.1',[int]$TimeoutMs = 500)
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect($Host,$Port,$null,$null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            return $true
        }
        $client.EndConnect($async) | Out-Null
        return $false
    } catch {
        return $true
    } finally {
        if ($client) { $client.Dispose() }
    }
}

Write-Host '✅ آغاز تشخیص محیط Windows ImportToSabt' -ForegroundColor Cyan

if ($IsLinux -or $IsMacOS) {
    Invoke-Failure 'این اسکریپت فقط در Windows پشتیبانی می‌شود.'
}

$osVersion = [System.Environment]::OSVersion
Write-Host ("سیستم‌عامل: {0}" -f $osVersion.VersionString)

$python = $null
try {
    $python = (Get-Command py -ErrorAction Stop)
    $versionOutput = & $python.Source -3.11 -c "import sys;print(sys.version)"
} catch {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Invoke-Failure 'Python 3.11 یافت نشد؛ دستور `winget install --id Python.Python.3.11` را اجرا کنید.'
    }
    $versionOutput = & $python.Source -c "import sys;print(sys.version)"
}
if (-not $versionOutput.StartsWith('3.11.')) {
    Invoke-Failure "نسخهٔ پایتون پشتیبانی نمی‌شود؛ خروجی: $versionOutput"
}
Write-Host ("Python 3.11 تأیید شد: {0}" -f $versionOutput)

$required = @('pip','git','openssl')
foreach ($tool in $required) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Invoke-Failure "ابزار الزامی یافت نشد: $tool"
    }
    Write-Host ("✅ ابزار یافت شد: {0} => {1}" -f $tool,$cmd.Source)
}

$vswhere = Get-Command 'vswhere.exe' -ErrorAction SilentlyContinue
$cl = Get-Command 'cl.exe' -ErrorAction SilentlyContinue
if (-not $vswhere -and -not $cl) {
    Invoke-Failure 'ابزارهای ساخت Visual Studio یافت نشد؛ Build Tools 2022 را نصب کنید.'
}
Write-Host '✅ ابزارهای ساخت Visual Studio در دسترس هستند.'

$docker = Get-Command 'docker' -ErrorAction SilentlyContinue
$wsl = Get-Command 'wsl.exe' -ErrorAction SilentlyContinue
if (-not $docker -and -not $wsl) {
    Invoke-Failure 'Docker یا WSL2 در دسترس نیست؛ یکی از آن‌ها را نصب/فعال کنید.'
}
if ($docker) { Write-Host '✅ Docker Desktop CLI شناسایی شد.' }
if ($wsl)   { Write-Host 'ℹ️ WSL2 قابل استفاده است.' }

foreach ($port in $CheckPorts) {
    if (-not (Test-PortFree -Port $port)) {
        Invoke-Failure "درگاه $port مشغول است؛ لطفاً فرایند مزاحم را متوقف کنید."
    }
    Write-Host ("✅ درگاه {0} آزاد است." -f $port)
}

Write-Host 'تشخیص با موفقیت به پایان رسید.' -ForegroundColor Green
