#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

[CmdletBinding()]
param(
    [string]$Base = 'http://127.0.0.1:25119',
    [string]$ServiceToken,
    [string]$MetricsToken,
    [int]$TimeoutSec = 20
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = (Resolve-Path -Path (Join-Path $scriptRoot '..')).Path
$exitCode   = 0

function Get-SimpleEnvValues {
    param([Parameter(Mandatory = $true)][string]$Path)
    $result = @{}
    if (-not (Test-Path -Path $Path)) { return $result }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $t = $line.Trim(); if([string]::IsNullOrWhiteSpace($t)) {continue}
        if($t.StartsWith('#')) {continue}
        $i = $t.IndexOf('='); if($i -lt 1){continue}
        $key = $t.Substring(0,$i).Trim().ToLowerInvariant()
        $val = $t.Substring($i+1).Trim()
        if ($val.StartsWith('"') -and $val.EndsWith('"') -and $val.Length -ge 2) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $result[$key] = $val
    }
    return $result
}

function Test-TcpPortOpen {
    param([Parameter(Mandatory=$true)][string]$TargetHost,[Parameter(Mandatory=$true)][int]$Port,[int]$TimeoutMs=500)
    $c=$null
    try{ $c=New-Object System.Net.Sockets.TcpClient; $a=$c.BeginConnect($TargetHost,$Port,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne($TimeoutMs)){return $false}
        $c.EndConnect($a) | Out-Null; return $true } catch { return $false } finally { if($c){$c.Dispose()} }
}

function Invoke-HttpHeadOrGet {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [hashtable]$Headers,
        [int]$TimeoutMs = 2000,
        [ValidateSet('GET','HEAD')][string]$Method = 'GET'
    )
    $creationError = $null
    $handler = $null
    $client  = $null
    try {
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.UseProxy = $false
        $handler.Proxy = $null
        $handler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
        $handler.AllowAutoRedirect = $false

        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.Timeout = [TimeSpan]::FromMilliseconds($TimeoutMs)
        $client.DefaultRequestHeaders.ExpectContinue = $false

        $applyHeaders = {
            param($request)
            if ($Headers) {
                foreach ($k in $Headers.Keys) {
                    $value = [string]$Headers[$k]
                    if (-not $request.Headers.TryAddWithoutValidation($k, $value)) {
                        if (-not $request.Content) {
                            $request.Content = New-Object System.Net.Http.StringContent('')
                            $request.Content.Headers.Clear()
                        }
                        $null = $request.Content.Headers.TryAddWithoutValidation($k, $value)
                    }
                }
            }
        }

        $sendRequest = {
            param([System.Net.Http.HttpMethod]$httpMethod)
            $cts = $null
            $request = $null
            $response = $null
            try {
                $cts = [System.Threading.CancellationTokenSource]::new()
                $cts.CancelAfter($TimeoutMs)
                $request = New-Object System.Net.Http.HttpRequestMessage($httpMethod, $Uri)
                & $applyHeaders $request
                $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cts.Token).GetAwaiter().GetResult()
                $status = [int]$response.StatusCode
                $snippet = ''
                if ($response.Content) {
                    $stream = $null
                    $reader = $null
                    try {
                        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                        if ($stream -and $stream.CanTimeout) {
                            try { $stream.ReadTimeout = $TimeoutMs } catch {}
                        }
                        if ($stream) {
                            $reader = New-Object System.IO.StreamReader($stream, [Text.Encoding]::UTF8, $true, 1024, $false)
                            $buffer = New-Object char[] 200
                            $readChars = $reader.Read($buffer, 0, $buffer.Length)
                            if ($readChars -gt 0) {
                                $snippet = New-Object string ($buffer, 0, $readChars)
                            }
                        }
                    } catch {
                        # Ignore snippet extraction issues
                    } finally {
                        if ($reader) { $reader.Dispose() }
                        if ($stream) { $stream.Dispose() }
                    }
                }
                return @{
                    StatusCode = $status
                    Content    = $snippet
                }
            } finally {
                if ($response) { $response.Dispose() }
                if ($request) { $request.Dispose() }
                if ($cts) { $cts.Dispose() }
            }
        }

        $headResult = $null
        $needGet = $false
        try {
            $headResult = & $sendRequest ([System.Net.Http.HttpMethod]::Head)
            if ($Method -eq 'GET') {
                if ($headResult.StatusCode -eq 200) {
                    return [pscustomobject]@{ StatusCode = $headResult.StatusCode; Content = $headResult.Content }
                }
                if ($headResult.StatusCode -eq 405 -or $headResult.StatusCode -ne 200) {
                    $needGet = $true
                }
            } else {
                if ($headResult.StatusCode -eq 405) {
                    $needGet = $true
                } else {
                    return [pscustomobject]@{ StatusCode = $headResult.StatusCode; Content = $headResult.Content }
                }
            }
        } catch {
            $needGet = ($Method -eq 'GET')
        }

        if ($needGet -or -not $headResult) {
            $getResult = & $sendRequest ([System.Net.Http.HttpMethod]::Get)
            return [pscustomobject]@{ StatusCode = $getResult.StatusCode; Content = $getResult.Content }
        }

        if ($headResult) {
            return [pscustomobject]@{ StatusCode = $headResult.StatusCode; Content = $headResult.Content }
        }
    } catch {
        $creationError = $_
    } finally {
        if ($client) { $client.Dispose() }
        if ($handler){ $handler.Dispose() }
    }

    $sec = [Math]::Ceiling($TimeoutMs / 1000.0)
    if ($sec -lt 1) { $sec = 1 }
    $methodsFallback = @('HEAD','GET')
    foreach ($fallbackMethod in $methodsFallback) {
        try {
            $args = @{ Uri = $Uri; Method = $fallbackMethod; UseBasicParsing = $true; TimeoutSec = $sec; ErrorAction = 'Stop' }
            if ($Headers) { $args['Headers'] = $Headers }
            $r = Invoke-WebRequest @args
            $statusCode = [int]$r.StatusCode
            if ($fallbackMethod -eq 'HEAD' -and $statusCode -eq 405) {
                continue
            }
            $body = ''
            if ($r.Content) {
                $body = $r.Content
                if ($body.Length -gt 200) { $body = $body.Substring(0, 200) }
            }
            return [pscustomobject]@{ StatusCode = $statusCode; Content = $body }
        } catch {
            if ($fallbackMethod -eq 'HEAD') {
                continue
            }
            throw
        }
    }

    if ($creationError) { throw $creationError }
    throw "درخواست به $Uri پاسخی دریافت نکرد."
}

function Write-ResponseSnippet {
    param([string]$Content)
    if ([string]::IsNullOrWhiteSpace($Content)) { return }
    $length = [Math]::Min(200, $Content.Length)
    $snippet = $Content.Substring(0, $length).Replace("`r", ' ').Replace("`n", ' ').Trim()
    Write-Host "… پاسخ: $snippet" -ForegroundColor DarkGray
}

function Get-PowerShellExecutable {
    $pwsh = Get-Command -Name 'pwsh' -ErrorAction SilentlyContinue
    if ($pwsh) { return $pwsh.Source }
    $winps = Get-Command -Name 'powershell.exe' -ErrorAction SilentlyContinue
    if ($winps) { return $winps.Source }
    throw 'هیچ‌یک از pwsh یا powershell.exe در PATH موجود نیستند.'
}

Push-Location -Path $repoRoot
try {
    $envFilePath = Join-Path $repoRoot '.env.dev'
    $envValues   = Get-SimpleEnvValues -Path $envFilePath

    # ✅ Prefer JSON object if present: IMPORT_TO_SABT_AUTH={"service_token": "...", "metrics_token": "..."}
    if (-not $ServiceToken -and $envValues.ContainsKey('import_to_sabt_auth')) {
        try { $authObj = $envValues['import_to_sabt_auth'] | ConvertFrom-Json
              if ($authObj.service_token) { $ServiceToken = "$($authObj.service_token)" } } catch {}
    }
    if (-not $MetricsToken -and $envValues.ContainsKey('import_to_sabt_auth')) {
        try { $authObj = $envValues['import_to_sabt_auth'] | ConvertFrom-Json
              if ($authObj.metrics_token) { $MetricsToken = "$($authObj.metrics_token)" } } catch {}
    }

    # Fallbacks (dev defaults)
    if (-not $ServiceToken) { $ServiceToken = 'dev-admin' }
    if (-not $MetricsToken) { $MetricsToken = 'dev-metrics' }

    $baseUri = $Base.TrimEnd('/')
    $hostUri = [System.Uri]::new($baseUri)
    $port    = $hostUri.Port
    $targetHost    = if ($hostUri.Host) { $hostUri.Host } else { '127.0.0.1' }

    if (-not (Test-TcpPortOpen -TargetHost $targetHost -Port $port)) {
        Write-Host "🔄 سرویس در دسترس نیست؛ تلاش برای اجرای Start-App.ps1" -ForegroundColor Yellow
        $startApp = Join-Path $repoRoot 'Start-App.ps1'
        if (-not (Test-Path -Path $startApp)) { throw "Start-App.ps1 در مسیر $startApp پیدا نشد." }

        $psExe = Get-PowerShellExecutable
        $args  = ($psExe -like '*pwsh*')
            ? @('-NoLogo','-NoProfile','-File',$startApp)
            : @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$startApp)

        $p = Start-Process -FilePath $psExe -ArgumentList $args -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "Start-App.ps1 با کد خروج $($p.ExitCode) خاتمه یافت." }
        Start-Sleep -Seconds 2
        if (-not (Test-TcpPortOpen -TargetHost $targetHost -Port $port -TimeoutMs 1000)) {
            throw "پورت $port روی $targetHost پس از اجرای Start-App.ps1 نیز باز نشد."
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    $readyUri = "$baseUri/readyz"
    $ready = $false
    Write-Host "→ checking /readyz ..." -ForegroundColor DarkGray
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $r = Invoke-HttpHeadOrGet -Uri $readyUri -TimeoutMs 2000 -Method 'HEAD'
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        }
        catch { Start-Sleep -Milliseconds 500 }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "مهلت $TimeoutSec ثانیه‌ای برای دریافت پاسخ 200 از /readyz به پایان رسید." }

    $healthUri    = "$baseUri/ui/health"
    $healthHeader = @{ Authorization = "Bearer $ServiceToken" }
    Write-Host "→ checking /ui/health ..." -ForegroundColor DarkGray
    $h = Invoke-HttpHeadOrGet -Uri $healthUri -Headers $healthHeader -TimeoutMs 3000
    if ($h.StatusCode -ne 200) {
        Write-ResponseSnippet -Content $h.Content
        throw "/ui/health پاسخ غیر 200 برگرداند (StatusCode=$($h.StatusCode))."
    }

    $metricsUri    = "$baseUri/metrics"
    $metricsHeader = @{ 'X-Metrics-Token' = $MetricsToken }
    Write-Host "→ checking /metrics ..." -ForegroundColor DarkGray
    $m = Invoke-HttpHeadOrGet -Uri $metricsUri -Headers $metricsHeader -TimeoutMs 3000
    if ($m.StatusCode -ne 200) {
        Write-ResponseSnippet -Content $m.Content
        throw "/metrics پاسخ غیر 200 برگرداند (StatusCode=$($m.StatusCode))."
    }

    Write-Host "✅ Smoke OK" -ForegroundColor Green
}
catch {
    $exitCode = 1
    Write-Error "❌ تست دود شکست خورد: $($_.Exception.Message)"
}
finally { Pop-Location }
exit $exitCode
