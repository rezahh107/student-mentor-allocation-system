#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Resolve script root robustly
$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) {
    $p = $MyInvocation.MyCommand.Path
    $scriptRoot = $p ? (Split-Path -Parent $p) : (Get-Location).Path
}

$exitCode = 0
Push-Location -Path $scriptRoot

try {
    $logs = Join-Path $scriptRoot 'logs'
    if (-not (Test-Path $logs)) { New-Item -Path $logs -ItemType Directory | Out-Null }
    
    # ایجاد دو فایل لاگ جداگانه
    $logFileOut = Join-Path $logs 'app-stdout.log'
    $logFileErr = Join-Path $logs 'app-stderr.log'
    
    $venvRoot    = Join-Path $scriptRoot '.venv'
    $venvScripts = Join-Path $venvRoot 'Scripts'
    $pythonExe   = Join-Path $venvScripts 'python.exe'
    
    if (-not (Test-Path $pythonExe)) {
        Write-Host "Virtual environment not found. Creating .venv ..." -ForegroundColor Yellow
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($py) { 
            & $py.Source -3.11 -m venv $venvRoot 
        }
        else {
            $sysPy = Get-Command python -ErrorAction SilentlyContinue
            if (-not $sysPy) { 
                throw "Neither 'py' launcher nor 'python' is available. Install Python 3.11+ or add it to PATH." 
            }
            & $sysPy.Source -m venv $venvRoot
        }
    }
    
    if (-not (Test-Path $pythonExe)) { 
        throw "python.exe was not found at $pythonExe after venv creation." 
    }
    
    # Environment for the app
    $env:PYTHONPATH       = Join-Path $scriptRoot 'src'
    $env:PYTHONUTF8       = '1'
    $env:PYTHONUNBUFFERED = '1'
    
    $envFile = Join-Path $scriptRoot '.env.dev'
    $args = @('-m','uvicorn','main:app','--host','127.0.0.1','--port','25119','--env-file',$envFile)
    
    # Ensure uvicorn exists in venv
    & $pythonExe -m uvicorn --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "uvicorn is not installed in the venv. Activate $venvRoot and install dependencies (e.g., 'pip install -r requirements.txt' or 'pip install uvicorn[standard]')."
    }
    
    # استفاده از دو فایل لاگ جداگانه
    Start-Process -FilePath $pythonExe `
        -ArgumentList $args `
        -WorkingDirectory $scriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logFileOut `
        -RedirectStandardError  $logFileErr | Out-Null
    
    Write-Host "Service started successfully (logs/app-stdout.log, logs/app-stderr.log)" -ForegroundColor Green
}
catch {
    $exitCode = 1
    $e = $PSItem
    $msg = if ($e -and $e.Exception) { 
        $e.Exception.Message 
    } elseif ($Error[0]) { 
        $Error[0].Exception.Message 
    } else { 
        'Unknown error occurred' 
    }
    Write-Host "ERROR: Service failed to start: $msg" -ForegroundColor Red
}
finally {
    Pop-Location
    exit $exitCode
}