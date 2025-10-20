#requires -Version 7.0
# Requires editable dev deps (AGENTS.md::8 Testing & CI Gates)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Convert-Digits {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    $map = @{
        '۰' = '0'; '۱' = '1'; '۲' = '2'; '۳' = '3'; '۴' = '4';
        '۵' = '5'; '۶' = '6'; '۷' = '7'; '۸' = '8'; '۹' = '9';
        '٠' = '0'; '١' = '1'; '٢' = '2'; '٣' = '3'; '٤' = '4';
        '٥' = '5'; '٦' = '6'; '٧' = '7'; '٨' = '8'; '٩' = '9'
    }
    $builder = New-Object System.Text.StringBuilder
    foreach ($ch in $Value.ToCharArray()) {
        if ($map.ContainsKey($ch)) {
            [void]$builder.Append($map[$ch])
        } else {
            [void]$builder.Append($ch)
        }
    }
    return $builder.ToString()
}

function Sanitize-EnvText {
    param([string]$Value)
    if ($null -eq $Value) { return '' }
    $text = [string]$Value
    $text = $text.Normalize([System.Text.NormalizationForm]::FormKC)
    $text = $text -replace 'ي','ی' -replace 'ك','ک'
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "[\u200b\u200c\u200d\ufeff]", '')
    $text = [System.Text.RegularExpressions.Regex]::Replace($text, "[\u0000-\u001f]", ' ')
    $text = Convert-Digits $text
    return $text.Trim()
}

function Strip-Quotes {
    param([string]$Value)
    if ($null -eq $Value) { return '' }
    if ($Value.Length -ge 2 -and (
            ($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
            ($Value.StartsWith("'") -and $Value.EndsWith("'"))
        )) {
        return $Value.Substring(1, $Value.Length - 2)
    }
    return $Value
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "CONFIG_MISSING: «پیکربندی ناقص است؛ فایل env یافت نشد.»"
    }
    $lines = Get-Content -LiteralPath $Path -Encoding UTF8
    foreach ($line in $lines) {
        if ($null -eq $line) { continue }
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $parts = $trimmed.Split('=', 2)
        if ($parts.Length -ne 2) { continue }
        $key = Sanitize-EnvText $parts[0]
        if (-not $key) { continue }
        $rawValue = Strip-Quotes $parts[1]
        $value = Sanitize-EnvText $rawValue
        Set-Item -Path "Env:$key" -Value $value
    }
}

function Ensure-RequiredEnv {
    param([string]$Name)
    $value = Sanitize-EnvText ([System.Environment]::GetEnvironmentVariable($Name))
    if (-not $value -or $value.ToLowerInvariant() -in @('null','none','undefined')) {
        throw "CONFIG_MISSING: «پیکربندی ناقص است؛ متغیر $Name خالی است.»"
    }
    Set-Item -Path "Env:$Name" -Value $value
}

function Resolve-Python {
    param([string]$ScriptRoot)
    $venvRoot = Join-Path $ScriptRoot '.venv'
    $pythonExe = Join-Path $venvRoot 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        if (-not (Test-Path -LiteralPath $venvRoot)) {
            $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
            if ($pyLauncher) {
                & $pyLauncher.Source -3.11 -m venv $venvRoot
            } else {
                $systemPython = Get-Command python -ErrorAction SilentlyContinue
                if (-not $systemPython) {
                    throw "PYTHON_MISSING: «مفسر Python در دسترس نیست.»"
                }
                & $systemPython.Source -m venv $venvRoot
            }
        }
    }
    if (Test-Path -LiteralPath $pythonExe) {
        return $pythonExe
    }
    $fallback = Get-Command python -ErrorAction SilentlyContinue
    if ($fallback) {
        return $fallback.Source
    }
    throw "PYTHON_MISSING: «مفسر Python در دسترس نیست.»"
}

$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) {
    $invocation = $MyInvocation.MyCommand.Path
    if ($invocation) {
        $scriptRoot = Split-Path -Parent $invocation
    } else {
        $scriptRoot = (Get-Location).Path
    }
}

    $exitCode = 0
    Push-Location -Path $scriptRoot
    try {
        if (-not (pip show fastapi 2>$null)) {
            python -m pip install -U pip setuptools wheel
            pip install -e .[dev] || pip install -e .
            if ($LASTEXITCODE -ne 0) {
                throw "INSTALL_FAILED: «نصب وابستگی‌ها تکمیل نشد.»"
            }
        }

        $logs = Join-Path $scriptRoot 'logs'
        if (-not (Test-Path -LiteralPath $logs)) {
            [void](New-Item -Path $logs -ItemType Directory)
        }

    $envFile = Join-Path $scriptRoot '.env.dev'
    Import-DotEnv -Path $envFile

    Ensure-RequiredEnv -Name 'DATABASE_URL'
    Ensure-RequiredEnv -Name 'REDIS_URL'
    Ensure-RequiredEnv -Name 'METRICS_TOKEN'

        Set-Item -Path Env:PYTHONUTF8 -Value '1'
        Set-Item -Path Env:PYTHONUNBUFFERED -Value '1'

    $portRaw = Sanitize-EnvText $Env:SMASM_PORT
    if (-not $portRaw) { $portRaw = '25119' }
    $parsed = 0
    if (-not [int]::TryParse($portRaw, [ref]$parsed)) { $portRaw = '25119' }
    Set-Item -Path Env:SMASM_PORT -Value $portRaw

    $pythonExe = Resolve-Python -ScriptRoot $scriptRoot

    $readinessArgs = @(
        '-m', 'windows_service.readiness_cli',
        '--check',
        '--attempts', '3',
        '--base-delay-ms', '150',
        '--timeout', '1.5'
    )
    $readinessOutput = & $pythonExe @readinessArgs 2>&1
    $readinessExit = $LASTEXITCODE
    if ($readinessExit -ne 0) {
        $detail = 'سرویس آماده نشد؛ وابستگی‌ها در دسترس نیستند.'
        try {
            $parsed = $readinessOutput | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -and $parsed.fa_error_envelope -and $parsed.fa_error_envelope.message) {
                $detail = [string]$parsed.fa_error_envelope.message
            }
        } catch {
            $null = $_
        }
        throw "READINESS_FAILED: «$detail»"
    }

    $stdoutLog = Join-Path $logs 'app-stdout.log'
    $stderrLog = Join-Path $logs 'app-stderr.log'

    $arguments = @('-m', 'windows_service.controller', 'run', '--port', $Env:SMASM_PORT)
    $startInfo = @{
        FilePath = $pythonExe
        ArgumentList = $arguments
        WorkingDirectory = $scriptRoot
        RedirectStandardOutput = $stdoutLog
        RedirectStandardError = $stderrLog
        NoNewWindow = $true
        PassThru = $true
    }
    $process = Start-Process @startInfo
    $process.WaitForExit()
    $exitCode = $process.ExitCode
}
catch {
    $err = $_.Exception
    $msg = if ($err -and $err.Message) { $err.Message } else { 'خطای ناشناخته رخ داد.' }
    if ($msg -like 'READINESS_FAILED*') {
        $exitCode = 2
    } else {
        $exitCode = 1
    }
    Write-Error "SERVICE_START_FAILED: $msg"
}
finally {
    Pop-Location
    exit $exitCode
}
