Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exitCode = 0

Push-Location -Path $scriptRoot
try {
    $logsDirectory = Join-Path $scriptRoot 'logs'
    if (-not (Test-Path -Path $logsDirectory)) {
        New-Item -Path $logsDirectory -ItemType Directory | Out-Null
    }

    $venvRoot    = Join-Path $scriptRoot '.venv'
    $pythonFiles = Join-Path $venvRoot 'Scripts'
    $pythonwPath = Join-Path $pythonFiles 'pythonw.exe'

    if (-not (Test-Path -Path $pythonwPath)) {
        Write-Error "pythonw.exe در مسیر $pythonwPath پیدا نشد؛ لطفاً ابتدا محیط مجازی را بسازید."
        $exitCode = 1
        return
    }

    # ✅ Guarantee imports from src/ even if the user didn't export PYTHONPATH
    $srcPath = Join-Path $scriptRoot 'src'
    $env:PYTHONPATH = $srcPath
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'

    $envFile  = Join-Path $scriptRoot '.env.dev'
    $logFile  = Join-Path $logsDirectory 'app.log'
    $arguments = @(
        '-m','uvicorn','main:app',
        '--host','127.0.0.1',
        '--port','25119',
        '--env-file',$envFile
    )

    Start-Process -FilePath $pythonwPath `
        -ArgumentList $arguments `
        -WorkingDirectory $scriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError  $logFile | Out-Null

    Write-Host "✅ سرویس با موفقیت اجرا شد (logs/app.log)"
}
catch {
    $exitCode = 1
    Write-Error "❌ اجرای سرویس ناموفق بود: $($_.Exception.Message)"
}
finally {
    Pop-Location
    exit $exitCode
}
