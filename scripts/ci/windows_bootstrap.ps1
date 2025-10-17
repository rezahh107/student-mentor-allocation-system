[CmdletBinding()]
param(
    [string]$PythonExecutable = "python",
    [string]$Requirements = "requirements-test.txt",
    [string]$VirtualEnvPath = ".venv",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = 'SilentlyContinue'

Write-Host "[bootstrap] Python executable: $PythonExecutable"
Write-Host "[bootstrap] Requirements file: $Requirements"

$resolvedRoot = Resolve-Path .
$venvDirectory = Join-Path $resolvedRoot $VirtualEnvPath
$artifactsDir = Join-Path $resolvedRoot "artifacts"
if (-not (Test-Path $artifactsDir)) {
    New-Item -ItemType Directory -Force -Path $artifactsDir | Out-Null
}

if (Test-Path $venvDirectory -PathType Container -and $Force.IsPresent) {
    Write-Host "[bootstrap] Removing existing virtualenv at $venvDirectory" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDirectory
}

if (-not (Test-Path $venvDirectory -PathType Container)) {
    Write-Host "[bootstrap] Creating virtualenv at $venvDirectory"
    & $PythonExecutable -m venv $venvDirectory
}

$activateScript = Join-Path $venvDirectory "Scripts/Activate.ps1"
if (-not (Test-Path $activateScript -PathType Leaf)) {
    throw "Virtualenv activation script not found: $activateScript"
}

Write-Host "[bootstrap] Activating virtualenv"
. $activateScript

Write-Host "[bootstrap] Upgrading pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel

if (-not (Test-Path $Requirements -PathType Leaf)) {
    throw "Requirements file not found: $Requirements"
}

Write-Host "[bootstrap] Installing dependencies from $Requirements"
python -m pip install -r $Requirements

Write-Host "[bootstrap] Validating installed packages"
python -m pip check

Write-Host "[bootstrap] Capturing pip freeze"
$freezePath = Join-Path $artifactsDir "pip-freeze.txt"
python -m pip freeze | Out-File -FilePath $freezePath -Encoding utf8
Write-Host "[bootstrap] Dependency snapshot stored at $freezePath"
