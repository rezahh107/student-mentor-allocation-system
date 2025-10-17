[CmdletBinding()]
param(
    [string[]]$Targets = @("tests/spec", "tests/windows", "tests/integration"),
    [string]$Config = "pytest.win.ini",
    [int]$MaxAttempts = 2,
    [double]$BaseDelaySeconds = 5,
    [string]$Namespace = "windows-ci"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = 'SilentlyContinue'

function Invoke-WithRetry {
    param(
        [scriptblock]$Operation,
        [int]$Attempts,
        [double]$Delay
    )

    $currentDelay = [double]$Delay
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            & $Operation
            if ($LASTEXITCODE -eq 0) {
                return 0
            }
            throw "Command exited with code $LASTEXITCODE"
        } catch {
            $errorMessage = $_.Exception.Message
            Write-Warning "Attempt $attempt/$Attempts failed: $errorMessage"
            try {
                python tools/ci/debug_context.py --reason retry --attempt $attempt --namespace $Namespace --message $errorMessage
            } catch {
                Write-Warning "Failed to collect retry debug context: $($_.Exception.Message)"
            }
            if ($attempt -ge $Attempts) {
                throw
            }
            $jitter = Get-Random -Minimum 0 -Maximum 2
            $sleep = [Math]::Max($currentDelay + $jitter, 1)
            Write-Host "Waiting $sleep seconds before retry"
            Start-Sleep -Seconds $sleep
            $currentDelay = [Math]::Min($currentDelay * 2, 30)
        }
    }
}

$resolvedRoot = Resolve-Path .
$activateScript = Join-Path $resolvedRoot ".venv/Scripts/Activate.ps1"
if (-not (Test-Path $activateScript -PathType Leaf)) {
    throw "Virtualenv activation script not found: $activateScript"
}
. $activateScript

if (-not (Test-Path $Config -PathType Leaf)) {
    throw "Pytest config not found: $Config"
}

python tools/ci/clean_state.py --phase pre --namespace "$Namespace"

$pytestArgs = @(
    "-c", $Config,
    "--rootdir", ".",
    "--confcutdir", "tests",
    "--maxfail", "1",
    "--tb", "short",
    "--disable-warnings",
    "--strict-markers",
    "--strict-config"
) + $Targets

$exitCode = 0
try {
    Invoke-WithRetry -Operation { python -m pytest @pytestArgs } -Attempts $MaxAttempts -Delay $BaseDelaySeconds | Out-Null
    $exitCode = $LASTEXITCODE
} catch {
    $exitCode = if ($LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 1 }
    python tools/ci/debug_context.py --reason failure --attempt $MaxAttempts --namespace $Namespace --message $_.Exception.Message
    throw
} finally {
    try {
        python tools/ci/clean_state.py --phase post --namespace "$Namespace"
    } catch {
        Write-Warning "Post-run cleanup failed: $($_.Exception.Message)"
    }
}

python tools/ci/debug_context.py --reason post-run --attempt $MaxAttempts --namespace $Namespace --message "pytest completed with code $exitCode"

if ($exitCode -ne 0) {
    throw "pytest failed with exit code $exitCode"
}
