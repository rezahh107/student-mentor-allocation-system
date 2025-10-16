#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Path = ".",
    [string]$Remote = "https://github.com/rezahh107/student-mentor-allocation-system.git",
    [string]$PythonVersion = "3.11",
    [string]$Venv = ".venv",
    [string]$EnvFile = ".env.dev",
    [int]$Port = 25119,
    [int]$Timeout = 30,
    [switch]$Fix,
    [switch]$Yes,
    [string]$Out,
    [switch]$Machine
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $env:CORRELATION_ID -or [string]::IsNullOrWhiteSpace($env:CORRELATION_ID)) {
    $env:CORRELATION_ID = [guid]::NewGuid().ToString()
}

function Resolve-CanonicalPath {
    param([Parameter(Mandatory)][string]$Base,[Parameter(Mandatory)][string]$Value)
    $candidate = if ([System.IO.Path]::IsPathRooted($Value)) {
        $Value
    } else {
        Join-Path -Path $Base -ChildPath $Value
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

function Select-PythonExecutable {
    foreach ($candidate in @("py","python","python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "پایتون در PATH یافت نشد؛ لطفاً Python $PythonVersion را نصب کنید."
}

$repoRoot = Resolve-CanonicalPath -Base (Get-Location).Path -Value $Path
$outDir = if ($Out) { Resolve-CanonicalPath -Base $repoRoot -Value $Out } else { Join-Path -Path $repoRoot -ChildPath "artifacts" }
$pythonExe = Select-PythonExecutable

$argsList = @(
    "-m","tools.windows_readiness",
    "--path",$repoRoot,
    "--remote",$Remote,
    "--python",$PythonVersion,
    "--venv",$Venv,
    "--env-file",$EnvFile,
    "--port",$Port,
    "--timeout",$Timeout,
    "--out",$outDir
)
if ($Fix) { $argsList += "--fix" }
if ($Yes) { $argsList += "--yes" }
if ($Machine) { $argsList += "--machine" }

Write-Host ("در حال اجرای ارزیابی آمادگی با شناسهٔ {0}" -f $env:CORRELATION_ID) -ForegroundColor Cyan
Write-Host ("python: {0}" -f $pythonExe) -ForegroundColor DarkGray

$process = Start-Process -FilePath $pythonExe -ArgumentList $argsList -WorkingDirectory $repoRoot -Wait -PassThru -NoNewWindow
$exitCode = $process.ExitCode

if ($exitCode -eq 0 -and -not $Machine) {
    $mdPath = Join-Path -Path $outDir -ChildPath "readiness_report.md"
    if (Test-Path $mdPath) {
        $code = Get-Command code -ErrorAction SilentlyContinue
        if ($code) {
            & $code.Source $mdPath | Out-Null
        } else {
            Write-Host ("گزارش: {0}" -f $mdPath) -ForegroundColor Green
        }
    }
}

exit $exitCode
