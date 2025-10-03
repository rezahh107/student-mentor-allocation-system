$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"

# Provide deterministic defaults for local smoke tests if not set by caller.
if (-not $env:IMPORT_TO_SABT_REDIS__DSN) {
    $env:IMPORT_TO_SABT_REDIS__DSN = "redis://localhost:6379/0"
}
if (-not $env:IMPORT_TO_SABT_REDIS__NAMESPACE) {
    $env:IMPORT_TO_SABT_REDIS__NAMESPACE = "import_to_sabt_smoke"
}
if (-not $env:IMPORT_TO_SABT_DATABASE__DSN) {
    $env:IMPORT_TO_SABT_DATABASE__DSN = "postgresql+asyncpg://localhost/import_to_sabt_smoke"
}
if (-not $env:IMPORT_TO_SABT_AUTH__SERVICE_TOKEN) {
    $env:IMPORT_TO_SABT_AUTH__SERVICE_TOKEN = "service-token-smoke"
}
if (-not $env:IMPORT_TO_SABT_AUTH__METRICS_TOKEN) {
    $env:IMPORT_TO_SABT_AUTH__METRICS_TOKEN = "metrics-token-smoke"
}

python tests/validate_structure.py
python tests/test_imports.py

$uvicornArgs = @(
    "-m", "uvicorn",
    "phase6_import_to_sabt.app.app_factory:create_application",
    "--factory",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--log-level", "warning"
)

$logDir = Join-Path $PSScriptRoot "tmp"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory | Out-Null
}
$stdoutLog = Join-Path $logDir "uvicorn.stdout.log"
$stderrLog = Join-Path $logDir "uvicorn.stderr.log"

$server = $null
try {
    $server = Start-Process -FilePath "python" -ArgumentList $uvicornArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    $baseUrl = "http://127.0.0.1:8000"

    $maxAttempts = 15
    $serverReady = $false
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Start-Sleep -Milliseconds (200 * $attempt)
        try {
            $health = Invoke-WebRequest -Uri "$baseUrl/healthz" -UseBasicParsing -Method Get -TimeoutSec 5
            if ($health.StatusCode -eq 200) {
                $serverReady = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }

    if (-not $serverReady) {
        throw "Uvicorn failed to respond on $baseUrl/healthz; check $stdoutLog and $stderrLog"
    }

    function Invoke-SmokeCheck {
        param(
            [string]$Name,
            [string]$Uri,
            [int[]]$ExpectedStatus,
            [hashtable]$Headers = @{}
        )

        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -Method Get -Headers $Headers -TimeoutSec 10
            $statusCode = [int]$response.StatusCode
            $body = $response.Content
        } catch {
            $errorResponse = $_.Exception.Response
            if ($null -ne $errorResponse) {
                $statusCode = [int]$errorResponse.StatusCode
                $reader = New-Object System.IO.StreamReader($errorResponse.GetResponseStream())
                $body = $reader.ReadToEnd()
            } else {
                throw
            }
        }

        if ($ExpectedStatus -contains $statusCode) {
            Write-Host "✅ $Name ($statusCode)"
        } else {
            Write-Host "❌ $Name expected $ExpectedStatus but received $statusCode"
            Write-Host "    Response snippet: $($body.Substring(0, [Math]::Min(200, $body.Length)))"
            throw "Smoke check failed"
        }

        return @{ Status = $statusCode; Body = $body }
    }

    Invoke-SmokeCheck -Name "GET /healthz" -Uri "$baseUrl/healthz" -ExpectedStatus @(200)
    Invoke-SmokeCheck -Name "GET /readyz" -Uri "$baseUrl/readyz" -ExpectedStatus @(200,503)

    $unauth = Invoke-SmokeCheck -Name "GET /metrics (no token)" -Uri "$baseUrl/metrics" -ExpectedStatus @(401,403)
    $metricsToken = $env:IMPORT_TO_SABT_AUTH__METRICS_TOKEN
    if (-not $metricsToken) {
        throw "IMPORT_TO_SABT_AUTH__METRICS_TOKEN must be set for authorised metrics smoke test"
    }
    $authHeaders = @{ "X-Metrics-Token" = $metricsToken }
    $authMetrics = Invoke-SmokeCheck -Name "GET /metrics (token)" -Uri "$baseUrl/metrics" -Headers $authHeaders -ExpectedStatus @(200)
    if (-not ($authMetrics.Body.StartsWith("# HELP") -or $authMetrics.Body.Contains("_total"))) {
        Write-Host "❌ /metrics response body missing Prometheus markers"
        throw "Metrics response validation failed"
    }
    Write-Host "✅ /metrics payload validated"

} finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        $server.WaitForExit()
    }
}
