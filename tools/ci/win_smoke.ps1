[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
chcp 65001 > $null

function Get-PythonInterpreter {
    param([string]$Root)
    $candidates = @(
        Join-Path -Path $Root -ChildPath ".venv\Scripts\python.exe",
        Join-Path -Path $Root -ChildPath ".venv/bin/python",
        "python"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return "python"
}

function New-DeterministicRandom {
    param([int]$Seed)
    return [System.Random]::new($Seed)
}

function Invoke-ReadinessProbe {
    param(
        [System.Diagnostics.Process]$ServerProcess,
        [int]$MaxRetries = 5,
        [int]$InitialDelay = 1,
        [System.Random]$Random = $(New-DeterministicRandom -Seed 373)
    )

    for ($attempt = 0; $attempt -lt $MaxRetries; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/healthz" -TimeoutSec 2 -ErrorAction Stop | Out-Null
            return $true
        } catch {
            if ($ServerProcess.HasExited) {
                throw "❌ خطا: فرایند uvicorn پیش از آماده‌سازی متوقف شد."
            }
            $delay = $InitialDelay * [math]::Pow(2, $attempt)
            $jitterMs = $Random.Next(100, 301)
            $delaySeconds = [math]::Round($delay + ($jitterMs / 1000.0), 3)
            Write-Host "⏳ Waiting server… retry $($attempt + 1)/$MaxRetries in $delaySeconds s" -ForegroundColor Yellow
            Start-Sleep -Seconds $delaySeconds
        }
    }

    return $false
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot ".." "..")
$python = Get-PythonInterpreter -Root $repoRoot

$server = $null
Push-Location $repoRoot
try {
    $arguments = @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning")
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $python
    foreach ($arg in $arguments) {
        $null = $startInfo.ArgumentList.Add($arg)
    }
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false

    $server = New-Object System.Diagnostics.Process
    $server.StartInfo = $startInfo
    if (-not $server.Start()) {
        throw "❌ راه‌اندازی uvicorn ناموفق بود."
    }

    if (-not (Invoke-ReadinessProbe -ServerProcess $server)) {
        throw "❌ سرویس در بازهٔ تعیین‌شده آماده نشد."
    }

    $healthStatus = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/healthz" -TimeoutSec 3).StatusCode
    $healthStatus | Out-Host

    $metricsStatus = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/metrics" -TimeoutSec 3).StatusCode
    $metricsStatus | Out-Host
} catch {
    if ($server -and -not $server.HasExited) {
        try {
            $server.Kill()
        } catch {
            Write-Warning $_
        }
    }
    Write-Error $_
    exit 1
} finally {
    if ($server -and -not $server.HasExited) {
        $server.Kill()
        $server.WaitForExit()
    }
    Pop-Location
}
