[CmdletBinding()]
param(
    [string]$VenvPath = (Join-Path $PSScriptRoot '..\\.venv'),
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\\.env')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not (Test-Path -Path $VenvPath)) {
    throw "Virtual environment not found at '$VenvPath'. Run 'py -3.11 -m venv .venv' and install dependencies first."
}

$activateScript = Join-Path $VenvPath 'Scripts\\Activate.ps1'
if (-not (Test-Path -Path $activateScript)) {
    throw "Activation script missing at '$activateScript'. Ensure the virtual environment was created with PowerShell support."
}

if (-not (Test-Path -Path $EnvFile)) {
    throw "Expected environment file '$EnvFile'. Copy '.env.example' to '.env' before running the dev server."
}

Write-Host "[dev] Activating virtual environment from $VenvPath" -ForegroundColor Cyan
. $activateScript

Write-Host "[dev] Confirmed .env at $EnvFile (loaded automatically by devserver.py)" -ForegroundColor Cyan

Push-Location -Path $repoRoot
try {
    $python = Get-Command python -ErrorAction Stop
    Write-Host "[dev] Launching devserver.py via $($python.Path)" -ForegroundColor Green
    & $python.Path (Join-Path $repoRoot 'devserver.py')
}
finally {
    Pop-Location
}
