#requires -Version 7.0
[CmdletBinding()]
param(
    [switch] $Force,
    [string] $RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Info {
    param([string] $Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Try-Command {
    param([string] $Name)
    try {
        Get-Command -Name $Name -ErrorAction Stop | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

$candidateRunId = if ([string]::IsNullOrWhiteSpace($RunId)) { $env:GITHUB_RUN_ID } else { $RunId }
if ([string]::IsNullOrWhiteSpace($candidateRunId)) {
    $candidateRunId = Get-Date -Format 'yyyyMMddHHmmssfff'
}
$sanitizedRunId = ($candidateRunId -replace '[^a-zA-Z0-9\-]', '')
if ([string]::IsNullOrWhiteSpace($sanitizedRunId)) {
    $sanitizedRunId = 'local'
}
Write-Info "Using RunId '$sanitizedRunId' for cleanup"

$containers = @(
    "sma-dev-redis-$sanitizedRunId",
    "sma-dev-postgres-$sanitizedRunId"
)
if (Try-Command -Name 'docker') {
    foreach ($name in $containers) {
        $exists = docker ps -a --filter "name=^$name$" --format '{{.ID}}'
        if ($LASTEXITCODE -ne 0) { continue }
        if (-not [string]::IsNullOrWhiteSpace($exists)) {
            Write-Info "Removing container $name"
            docker rm -f $name | Out-Null
        }
    }
}

$reportsPath = Join-Path (Get-Location) 'reports/ci'
if (Test-Path -LiteralPath $reportsPath) {
    Write-Info "Cleaning $reportsPath"
    Remove-Item -LiteralPath $reportsPath -Recurse -Force
}

if ($Force) {
    $venvPath = Join-Path (Get-Location) '.venv'
    if (Test-Path -LiteralPath $venvPath) {
        Write-Info "Removing $venvPath due to -Force"
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }
}
