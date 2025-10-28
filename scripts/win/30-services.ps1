[CmdletBinding()]
param(
    [ValidateSet('Start','Stop','Cleanup')]
    [string]$Action = 'Start',
    [ValidateSet('Docker','ValidateLocal')]
    [string]$Mode = 'Docker',
    [string]$ComposeFile = 'docker-compose.dev.yml',
    [int]$MaxRetries = 12,
    [int]$BaseDelayMilliseconds = 200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$script:CorrelationId = ([Guid]::NewGuid()).ToString('n')
$script:ReportsRoot = Join-Path (Get-Location) 'reports/win-smoke'
if (-not (Test-Path $script:ReportsRoot)) {
    New-Item -ItemType Directory -Force -Path $script:ReportsRoot | Out-Null
}
$script:LogPath = Join-Path $script:ReportsRoot 'services-log.jsonl'
$script:MetricsPath = Join-Path $script:ReportsRoot 'services-metrics.prom'
$script:RetryCounts = @{}

function Get-ExecutablePath {
    param([System.Management.Automation.CommandInfo]$Command)
    if (-not $Command) { return $null }
    if ($Command -is [System.Management.Automation.ApplicationInfo]) {
        return $Command.Source
    }
    return $Command.Definition
}

function Write-JsonLog {
    <# Evidence: AGENTS.md::7 Observability; Evidence: AGENTS.md::10 User-Visible Errors #>
    param(
        [string]$Event,
        [hashtable]$Data
    )

    $payload = [ordered]@{
        correlation_id = $script:CorrelationId
        event = $Event
        monotonic_ticks = [System.Diagnostics.Stopwatch]::GetTimestamp()
        stopwatch_frequency = [System.Diagnostics.Stopwatch]::Frequency
    }
    foreach ($key in $Data.Keys) {
        $payload[$key] = $Data[$key]
    }
    $json = ($payload | ConvertTo-Json -Depth 6 -Compress)
    Add-Content -Path $script:LogPath -Value $json -Encoding UTF8
}

function Add-RetryMetric {
    param([string]$Service,[int]$Attempt)
    if (-not $script:RetryCounts.ContainsKey($Service)) {
        $script:RetryCounts[$Service] = 0
    }
    if ($Attempt -gt 0) {
        $script:RetryCounts[$Service] += 1
    }
}

function Export-Metrics {
    <# Evidence: AGENTS.md::8 Testing & CI Gates #>
    $lines = @()
    foreach ($service in $script:RetryCounts.Keys) {
        $lines += "win_services_retry_attempts_total{service=\"$service\"} $($script:RetryCounts[$service])"
    }
    if (-not $lines) {
        $lines = @('win_services_retry_attempts_total{service="redis"} 0','win_services_retry_attempts_total{service="postgres"} 0')
    }
    Set-Content -Path $script:MetricsPath -Value $lines -Encoding UTF8
}

function Get-DeterministicDelay {
    param([string]$Service,[int]$Attempt)
    $attemptIndex = [Math]::Max(1,$Attempt)
    $base = [Math]::Min(8000, $BaseDelayMilliseconds * [Math]::Pow(2, $attemptIndex - 1))
    $seedBytes = [System.Text.Encoding]::UTF8.GetBytes("$Service::$attemptIndex")
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($seedBytes)
    $fraction = $hash[0] / 255
    $jitter = 150 * $fraction
    return ([Math]::Min(10000, $base + $jitter) / 1000.0)
}

function Test-TcpOpen {
    param([string]$Host = '127.0.0.1',[int]$Port,[int]$TimeoutMs = 500)
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect($Host,$Port,$null,$null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            return $false
        }
        $client.EndConnect($async) | Out-Null
        return $true
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Invoke-WithRetry {
    <# Evidence: AGENTS.md::3 Absolute Guardrails (retry) #>
    param(
        [string]$Service,
        [scriptblock]$Operation,
        [int]$Retries
    )

    for ($attempt = 1; $attempt -le $Retries; $attempt++) {
        try {
            $result = & $Operation
            Add-RetryMetric -Service $Service -Attempt ($attempt - 1)
            return $result
        } catch {
            Add-RetryMetric -Service $Service -Attempt 1
            $delay = Get-DeterministicDelay -Service $Service -Attempt $attempt
            Write-JsonLog -Event 'retry' -Data @{ service = $Service; attempt = $attempt; delay_seconds = [Math]::Round($delay,3); message = $_.Exception.Message }
            if ($attempt -eq $Retries) {
                throw
            }
            Start-Sleep -Seconds $delay
        }
    }
}

function Assert-DockerAvailable {
    $docker = Get-Command 'docker' -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw 'Docker Desktop نصب نشده یا در PATH نیست.'
    }
}

function Start-Services {
    param(
        [string]$ServiceMode = $Mode,
        [string]$ServiceComposeFile = $ComposeFile,
        [int]$ServiceMaxRetries = $MaxRetries
    )
    Write-JsonLog -Event 'start' -Data @{ action = 'Start'; mode = $ServiceMode }
    if ($ServiceMode -eq 'ValidateLocal') {
        foreach ($service in @(
                @{ name = 'redis'; port = 6379 },
                @{ name = 'postgres'; port = 5432 }
            )) {
            Invoke-WithRetry -Service $service.name -Retries $ServiceMaxRetries -Operation {
                if (Test-TcpOpen -Port $service.port) {
                    Write-JsonLog -Event 'ready' -Data @{ service = $service.name; port = $service.port; mode = 'local' }
                    return $true
                }
                throw "اتصال به سرویس $($service.name) برقرار نشد."
            } | Out-Null
        }
        return
    }

    Assert-DockerAvailable
    if (-not (Test-Path $ServiceComposeFile)) {
        throw "فایل compose یافت نشد: $ServiceComposeFile"
    }
    docker compose -f $ServiceComposeFile up -d redis postgres | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'اجرای docker compose با خطا پایان یافت.'
    }

    foreach ($serviceName in @('redis','postgres')) {
        Invoke-WithRetry -Service $serviceName -Retries $ServiceMaxRetries -Operation {
            $raw = docker compose -f $ServiceComposeFile ps --format json $serviceName
            if ($LASTEXITCODE -ne 0) {
                throw "خواندن وضعیت سرویس $serviceName شکست خورد."
            }
            $parsed = @($raw | ConvertFrom-Json)
            $record = $null
            if ($parsed.Count -ge 1) { $record = $parsed[0] }
            if ($null -ne $record) {
                $state = $record.State
                $health = $record.Health
                Write-JsonLog -Event 'probe' -Data @{ service = $serviceName; state = $state; health = $health }
                if ($health -eq 'healthy' -or $state -eq 'running') {
                    Write-JsonLog -Event 'ready' -Data @{ service = $serviceName; state = $state; health = $health }
                    return $true
                }
            }
            throw "سرویس $serviceName هنوز آماده نیست."
        } | Out-Null
    }
}

function Stop-Services {
    param(
        [string]$ServiceMode = $Mode,
        [string]$ServiceComposeFile = $ComposeFile
    )
    Write-JsonLog -Event 'stop' -Data @{ action = 'Stop'; mode = $ServiceMode }
    if ($ServiceMode -eq 'Docker') {
        Assert-DockerAvailable
        if (Test-Path $ServiceComposeFile) {
            docker compose -f $ServiceComposeFile stop redis postgres | Out-Null
        }
    }
}

function Cleanup-State {
    param(
        [string]$ServiceMode = $Mode,
        [string]$ServiceComposeFile = $ComposeFile
    )
    Write-JsonLog -Event 'cleanup' -Data @{ action = 'Cleanup'; mode = $ServiceMode }
    if ($ServiceMode -eq 'Docker') {
        Assert-DockerAvailable
        if (Test-Path $ServiceComposeFile) {
            docker compose -f $ServiceComposeFile down -v --remove-orphans | Out-Null
        }
        return
    }

    $redisCli = Get-Command 'redis-cli' -ErrorAction SilentlyContinue
    if ($redisCli) {
        $redisPath = Get-ExecutablePath -Command $redisCli
        if ($redisPath) {
            & $redisPath FLUSHALL | Out-Null
        }
    } else {
        Write-JsonLog -Event 'cleanup_warning' -Data @{ tool = 'redis-cli'; message = 'redis-cli یافت نشد.' }
    }

    $psql = Get-Command 'psql' -ErrorAction SilentlyContinue
    if ($psql) {
        $psqlPath = Get-ExecutablePath -Command $psql
        if ($psqlPath) {
            & $psqlPath -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS import_to_sabt;" postgres | Out-Null
            & $psqlPath -v ON_ERROR_STOP=1 -c "CREATE DATABASE import_to_sabt;" postgres | Out-Null
        }
    } else {
        Write-JsonLog -Event 'cleanup_warning' -Data @{ tool = 'psql'; message = 'psql یافت نشد.' }
    }
}

function Invoke-Main {
    switch ($Action) {
        'Start' { Start-Services -ServiceMode $Mode -ServiceComposeFile $ComposeFile -ServiceMaxRetries $MaxRetries }
        'Stop' { Stop-Services -ServiceMode $Mode -ServiceComposeFile $ComposeFile }
        'Cleanup' { Cleanup-State -ServiceMode $Mode -ServiceComposeFile $ComposeFile }
    }
    Export-Metrics
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-Main
    } catch {
        Write-JsonLog -Event 'failure' -Data @{ action = $Action; message = $_.Exception.Message }
        Export-Metrics
        throw
    }
}
