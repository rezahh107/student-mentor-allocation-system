[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$StateDir = 'tmp\win-app',
    [ValidateSet('Docker','ValidateLocal')]
    [string]$ServiceMode = 'Docker',
    [string]$ComposeFile = 'docker-compose.dev.yml',
    [switch]$SkipServiceManagement
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$serviceScript = Join-Path $PSScriptRoot '30-services.ps1'
. $serviceScript

$reportsRoot = Join-Path (Get-Location) 'reports/win-smoke'
if (-not (Test-Path $reportsRoot)) {
    New-Item -ItemType Directory -Force -Path $reportsRoot | Out-Null
}
$logPath = Join-Path $reportsRoot 'smoke-log.jsonl'
$summaryPath = Join-Path $reportsRoot 'smoke-summary.json'
$httpDetailPath = Join-Path $reportsRoot 'http-responses.json'

$correlationId = ([Guid]::NewGuid()).ToString('n')

function Write-SmokeArtifact {
    <# Evidence: AGENTS.md::6 Atomic I/O; Evidence: AGENTS.md::10 User-Visible Errors #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $directory = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($directory) -and -not (Test-Path $directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    $tempPath = "$Path.part"
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $fileStream = [System.IO.FileStream]::new($tempPath,[System.IO.FileMode]::Create,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
    try {
        $writer = [System.IO.StreamWriter]::new($fileStream,$encoding)
        try {
            $writer.Write($Content)
        } finally {
            $writer.Flush()
            $fileStream.Flush($true)
            $writer.Dispose()
        }
    } finally {
        $fileStream.Dispose()
    }
    Move-Item -Force -Path $tempPath -Destination $Path
}

function Write-SmokeLog {
    param([string]$Event,[hashtable]$Data)
    $payload = [ordered]@{
        correlation_id = $correlationId
        event = $Event
        monotonic_ticks = [System.Diagnostics.Stopwatch]::GetTimestamp()
        stopwatch_frequency = [System.Diagnostics.Stopwatch]::Frequency
    }
    foreach ($key in $Data.Keys) {
        $payload[$key] = $Data[$key]
    }
    $json = ($payload | ConvertTo-Json -Depth 6 -Compress)
    Add-Content -Path $logPath -Value $json -Encoding UTF8
}

function Import-DotEnv {
    param([string]$Path)
    $result = @{}
    if (-not (Test-Path $Path)) { return $result }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#')) { continue }
        $idx = $text.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $text.Substring(0,$idx).Trim()
        $value = $text.Substring($idx+1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
            $value = $value.Substring(1,$value.Length-2)
        }
        $result[$key] = $value
    }
    return $result
}

function Mask-Token {
    param([string]$Token)
    if ([string]::IsNullOrWhiteSpace($Token)) { return '' }
    if ($Token.Length -le 4) { return '***' }
    return "***$($Token.Substring($Token.Length-4))"
}

function Invoke-Http {
    param(
        [System.Net.Http.HttpClient]$Client,
        [string]$Method,
        [string]$Url,
        [int[]]$ExpectedStatuses,
        [hashtable]$Headers,
        [string]$Body,
        [string]$Label
    )

    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method),$Url)
            if ($Body) {
                $request.Content = [System.Net.Http.StringContent]::new($Body,[System.Text.Encoding]::UTF8,'application/json')
            }
            if ($Headers) {
                foreach ($key in $Headers.Keys) {
                    $val = [string]$Headers[$key]
                    if (-not $request.Headers.TryAddWithoutValidation($key,$val)) {
                        if (-not $request.Content) {
                            $request.Content = [System.Net.Http.StringContent]::new('',[System.Text.Encoding]::UTF8,'application/json')
                        }
                        $null = $request.Content.Headers.TryAddWithoutValidation($key,$val)
                    }
                }
            }

            $response = $Client.SendAsync($request).GetAwaiter().GetResult()
            $status = [int]$response.StatusCode
            $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $maskedHeaders = @{}
            if ($Headers) {
                foreach ($key in $Headers.Keys) {
                    $maskedHeaders[$key] = Mask-Token -Token $Headers[$key]
                }
            }
            Write-SmokeLog -Event 'http_response' -Data @{ label = $Label; status = $status; attempt = $attempt; headers = $maskedHeaders }
            if ($ExpectedStatuses -contains $status) {
                return @{ Status = $status; Body = $content }
            }
            if ($status -ge 500 -and $attempt -lt $maxAttempts) {
                $delay = [Math]::Min(3,[Math]::Pow(2,$attempt) * 0.2)
                Start-Sleep -Seconds $delay
                continue
            }
            throw "کد وضعیت غیرمنتظره: $status (انتظار: $($ExpectedStatuses -join ','))"
        } catch {
            Write-SmokeLog -Event 'http_retry' -Data @{ label = $Label; attempt = $attempt; message = $_.Exception.Message }
            if ($attempt -ge $maxAttempts) { throw }
            $delay = [Math]::Min(3,[Math]::Pow(2,$attempt) * 0.2)
            Start-Sleep -Seconds $delay
        }
    }
}

function Assert {
    param([bool]$Condition,[string]$Message)
    if (-not $Condition) { throw $Message }
}

$envFile = Join-Path (Get-Location) '.env'
$envMap = Import-DotEnv -Path $envFile
$serviceToken = [System.Environment]::GetEnvironmentVariable('IMPORT_TO_SABT_AUTH__SERVICE_TOKEN')
if (-not $serviceToken) { $serviceToken = $envMap['IMPORT_TO_SABT_AUTH__SERVICE_TOKEN'] }
if (-not $serviceToken) { $serviceToken = 'local-service-token' }

$stateFile = Join-Path $StateDir 'state.json'
if (Test-Path $stateFile) {
    try {
        $stateJson = Get-Content -Path $stateFile -Encoding UTF8 | ConvertFrom-Json
        if ($stateJson.host -and $stateJson.port) {
            $BaseUrl = "http://$($stateJson.host):$($stateJson.port)"
        }
    } catch {
        Write-SmokeLog -Event 'state_warning' -Data @{ message = $_.Exception.Message }
    }
}

$handler = [System.Net.Http.HttpClientHandler]::new()
$handler.UseProxy = $false
$client = [System.Net.Http.HttpClient]::new($handler)
$client.Timeout = [TimeSpan]::FromSeconds(10)

$httpResults = [System.Collections.Generic.List[object]]::new()

if (-not $SkipServiceManagement) {
    Start-Services -ServiceMode $ServiceMode -ServiceComposeFile $ComposeFile -ServiceMaxRetries 12
}

try {
    Write-SmokeLog -Event 'suite_start' -Data @{ base_url = $BaseUrl; mode = $ServiceMode }

    Write-Host "🔍 بررسی /healthz"
    $health = Invoke-Http -Client $client -Method 'GET' -Url "$BaseUrl/healthz" -ExpectedStatuses @(200) -Headers @{} -Body $null -Label 'healthz'
    $httpResults.Add(@{ path = '/healthz'; status = $health.Status }) | Out-Null
    $healthJson = $health.Body | ConvertFrom-Json
    Assert ($healthJson.status -eq 'ok') 'پاسخ healthz نامعتبر است.'

    Write-Host "🔍 بررسی /readyz"
    $ready = Invoke-Http -Client $client -Method 'GET' -Url "$BaseUrl/readyz" -ExpectedStatuses @(200) -Headers @{} -Body $null -Label 'readyz'
    $httpResults.Add(@{ path = '/readyz'; status = $ready.Status }) | Out-Null
    $readyJson = $ready.Body | ConvertFrom-Json
    Assert ($readyJson.status -eq 'ready') 'پاسخ readyz نشان‌دهندهٔ آمادگی نیست.'

    Write-Host "🔍 بررسی /docs"
    $docs = Invoke-Http -Client $client -Method 'GET' -Url "$BaseUrl/docs" -ExpectedStatuses @(200) -Headers @{} -Body $null -Label 'docs'
    $httpResults.Add(@{ path = '/docs'; status = $docs.Status }) | Out-Null

    Write-Host "🔍 بررسی /metrics"
    $metricsOk = Invoke-Http -Client $client -Method 'GET' -Url "$BaseUrl/metrics" -ExpectedStatuses @(200) -Headers @{} -Body $null -Label 'metrics_ok'
    $httpResults.Add(@{ path = '/metrics'; status = $metricsOk.Status; label = 'public' }) | Out-Null
    Assert ($metricsOk.Body -like '*# HELP*') 'خروجی متریک الگوی Prometheus ندارد.'

    Write-Host "🔍 فراخوانی POST /api/jobs"
    $authHeaders = @{ 'Authorization' = "Bearer $serviceToken"; 'Content-Type' = 'application/json' }
    $jobPayload = '{"center":1}'
    $job = Invoke-Http -Client $client -Method 'POST' -Url "$BaseUrl/api/jobs" -ExpectedStatuses @(200) -Headers $authHeaders -Body $jobPayload -Label 'jobs_post'
    $httpResults.Add(@{ path = '/api/jobs'; status = $job.Status }) | Out-Null
    $jobJson = $job.Body | ConvertFrom-Json
    $chain = ($jobJson.middleware_chain | ForEach-Object { $_ })
    # Evidence: tests/middleware/test_order_post.py::test_order_rate_idem_auth
    Assert ($chain -and $chain.Count -eq 3 -and $chain[0] -eq 'RateLimit' -and $chain[1] -eq 'Idempotency' -and $chain[2] -eq 'Auth') 'زنجیرهٔ middleware نامعتبر است.'
    Assert ($jobJson.role -eq 'ADMIN') 'نقش برگشتی ADMIN نیست.'

    Write-Host "🔍 بررسی GET /api/exports/csv"
    $exports = Invoke-Http -Client $client -Method 'GET' -Url "$BaseUrl/api/exports/csv" -ExpectedStatuses @(200) -Headers $authHeaders -Body $null -Label 'exports_csv'
    $httpResults.Add(@{ path = '/api/exports/csv'; status = $exports.Status }) | Out-Null

    Write-Host '✅ تست دود با موفقیت انجام شد.' -ForegroundColor Green
    Write-SmokeLog -Event 'suite_success' -Data @{ metrics_status = $metricsOk.Status }
} finally {
    $client.Dispose()
    $handler.Dispose()

    $summary = [ordered]@{
        correlation_id = $correlationId
        base_url = $BaseUrl
        requests = $httpResults
    } | ConvertTo-Json -Depth 4
    Write-SmokeArtifact -Path $summaryPath -Content $summary
    Write-SmokeArtifact -Path $httpDetailPath -Content ($httpResults | ConvertTo-Json -Depth 4)

    if (-not $SkipServiceManagement) {
        Cleanup-State -ServiceMode $ServiceMode -ServiceComposeFile $ComposeFile
        Stop-Services -ServiceMode $ServiceMode -ServiceComposeFile $ComposeFile
    }
}
