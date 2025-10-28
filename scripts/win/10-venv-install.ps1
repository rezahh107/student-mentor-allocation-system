[CmdletBinding()]
param(
    [string]$VenvPath = '.venv',
    [string]$ConstraintsPath = 'constraints-win.txt',
    [string[]]$RequirementFiles = @('requirements.txt'),
    [switch]$Recreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Resolve-Python311 {
    try {
        return (Get-Command py -ErrorAction Stop), @('-3.11')
    } catch {
        $python = Get-Command python -ErrorAction Stop
        $version = & $python.Source -c "import sys;print(sys.version)"
        if (-not $version.StartsWith('3.11.')) {
            throw "Python 3.11 یافت نشد؛ خروجی: $version"
        }
        return $python, @()
    }
}

$pythonCmd,$prefixArgs = Resolve-Python311

if ($Recreate -and (Test-Path $VenvPath)) {
    Remove-Item -Path $VenvPath -Recurse -Force
}

if (-not (Test-Path $VenvPath)) {
    Write-Host "ایجاد محیط مجازی در $VenvPath"
    & $pythonCmd.Source @($prefixArgs + @('-m','venv',$VenvPath))
}

$venvPython = Join-Path (Resolve-Path $VenvPath) 'Scripts/python.exe'
if (-not (Test-Path $venvPython)) {
    throw "محیط مجازی ایجاد نشد؛ مسیر یافت نشد: $venvPython"
}

Write-Host "Python مجازی: $venvPython"

$constraintArgs = @()
if ($ConstraintsPath -and (Test-Path $ConstraintsPath)) {
    $constraintArgs = @('--constraint', (Resolve-Path $ConstraintsPath))
}

function Invoke-Pip {
    param([string[]]$Args)
    & $venvPython -m pip @Args
}

Invoke-Pip @('install','--upgrade','pip','setuptools','wheel')

foreach ($req in $RequirementFiles) {
    if (-not (Test-Path $req)) {
        throw "فایل نیازمندی یافت نشد: $req"
    }
    Write-Host "نصب پکیج‌ها از $req"
    Invoke-Pip ((@('install','-r',(Resolve-Path $req))) + $constraintArgs)
}

Invoke-Pip ((@('install','-e','.')) + $constraintArgs)
Invoke-Pip ((@('install','tzdata==2025.2')) + $constraintArgs)

$uvloopInstalled = $false
try {
    & $venvPython -m pip show uvloop | Out-Null
    $uvloopInstalled = $LASTEXITCODE -eq 0
} catch {
    $uvloopInstalled = $false
}
if ($uvloopInstalled) {
    Write-Warning 'uvloop روی Windows پشتیبانی نمی‌شود؛ در حال حذف بسته.'
    Invoke-Pip @('uninstall','-y','uvloop')
}

Invoke-Pip @('check')
Write-Host 'محیط مجازی آماده است.' -ForegroundColor Green
