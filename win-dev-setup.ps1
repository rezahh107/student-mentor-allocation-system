#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$Base = 'http://127.0.0.1:25119',
    [string]$ServiceToken,
    [string]$MetricsToken,
    [int]$TimeoutSec = 20,
    [string]$StartAppPath,
    [string[]]$StartAppArgs,
    [switch]$SkipStartApp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) {
    $p = $MyInvocation.MyCommand.Path
    $scriptRoot = $p ? (Split-Path -Parent $p) : (Get-Location).Path
}

function Find-FileUpwards {
    param([Parameter(Mandatory)][string]$StartDir,[Parameter(Mandatory)][string]$FileName,[int]$MaxDepth=3)
    $d = $StartDir
    for ($i=0; $i -le $MaxDepth; $i++) {
        $path = Join-Path $d $FileName
        if (Test-Path $path) { return (Resolve-Path $path).Path }
        $parent = Split-Path -Parent $d
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $d) { break }
        $d = $parent
    }
    return $null
}

$repoRoot = $scriptRoot
try {
    if (Test-Path (Join-Path $scriptRoot '.git')) { $repoRoot = $scriptRoot }
    else {
        $up = (Resolve-Path (Join-Path $scriptRoot '..')).Path
        if (Test-Path (Join-Path $up '.git')) { $repoRoot = $up }
    }
} catch { $repoRoot = $scriptRoot }

function Get-SimpleEnvValues {
    param([Parameter(Mandatory)][string]$Path)
    $r = @{}
    if (-not (Test-Path $Path)) { return $r }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($t) -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('='); if ($i -lt 1) { continue }
        $k = $t.Substring(0,$i).Trim().ToLowerInvariant()
        $v = $t.Substring($i+1).Trim()
        if ($v.StartsWith('"') -and $v.EndsWith('"') -and $v.Length -ge 2) { $v = $v.Substring(1,$v.Length-2) }
        $r[$k] = $v
    }
    return $r
}

function Test-TcpPortOpen {
    param([Parameter(Mandatory)][string]$TargetHost,[Parameter(Mandatory)][int]$Port,[int]$TimeoutMs=500)
    $c = $null
    try {
        $c = [System.Net.Sockets.TcpClient]::new()
        $a = $c.BeginConnect($TargetHost,$Port,$null,$null)
        if (-not $a.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $c.EndConnect($a) | Out-Null
        return $true
    } catch { return $false } finally { if ($c) { $c.Dispose() } }
}

function Invoke-HttpHeadOrGet {
    param([Parameter(Mandatory)][string]$Uri,[hashtable]$Headers,[int]$TimeoutMs=2000,[ValidateSet('GET','HEAD')][string]$Method='GET')
    $creationError = $null; $handler = $null; $client = $null
    try {
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.UseProxy = $false; $handler.Proxy = $null
        $handler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
        $handler.AllowAutoRedirect = $false
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromMilliseconds($TimeoutMs)
        $client.DefaultRequestHeaders.ExpectContinue = $false

        $applyHeaders = {
            param($request)
            if ($Headers) {
                foreach ($k in $Headers.Keys) {
                    $val = [string]$Headers[$k]
                    if (-not $request.Headers.TryAddWithoutValidation($k,$val)) {
                        if (-not $request.Content) { $request.Content = [System.Net.Http.StringContent]::new(''); $request.Content.Headers.Clear() }
                        $null = $request.Content.Headers.TryAddWithoutValidation($k,$val)
                    }
                }
            }
        }

        $sendRequest = {
            param([System.Net.Http.HttpMethod]$httpMethod)
            $cts=$null; $request=$null; $response=$null
            try {
                $cts = [System.Threading.CancellationTokenSource]::new(); $cts.CancelAfter($TimeoutMs)
                $request = [System.Net.Http.HttpRequestMessage]::new($httpMethod,$Uri)
                & $applyHeaders $request
                $response = $client.SendAsync($request,[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead,$cts.Token).GetAwaiter().GetResult()
                $status  = [int]$response.StatusCode
                $snippet = ''
                if ($response.Content) {
                    $stream=$null; $reader=$null
                    try {
                        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                        if ($stream -and $stream.CanTimeout) { try { $stream.ReadTimeout = $TimeoutMs } catch {} }
                        if ($stream) {
                            $reader  = [System.IO.StreamReader]::new($stream,[System.Text.Encoding]::UTF8,$true,1024,$false)
                            $buffer  = New-Object char[] 200
                            $readLen = $reader.Read($buffer,0,$buffer.Length)
                            if ($readLen -gt 0) { $snippet = New-Object string ($buffer,0,$readLen) }
                        }
                    } catch {} finally { if ($reader){$reader.Dispose()}; if ($stream){$stream.Dispose()} }
                }
                return [pscustomobject]@{ StatusCode=$status; Content=$snippet }
            } finally { if ($response){$response.Dispose()}; if ($request){$request.Dispose()}; if ($cts){$cts.Dispose()} }
        }

        $headResult=$null; $needGet=$false
        try {
            $headResult = & $sendRequest ([System.Net.Http.HttpMethod]::Head)
            if ($Method -eq 'GET') {
                if ($headResult.StatusCode -eq 200) { return [pscustomobject]@{ StatusCode=$headResult.StatusCode; Content=$headResult.Content } }
                if ($headResult.StatusCode -eq 405 -or $headResult.StatusCode -ne 200) { $needGet = $true }
            } else {
                if ($headResult.StatusCode -eq 405) { $needGet = $true } else { return [pscustomobject]@{ StatusCode=$headResult.StatusCode; Content=$headResult.Content } }
            }
        } catch { $needGet = ($Method -eq 'GET') }

        if ($needGet -or -not $headResult) {
            $getResult = & $sendRequest ([System.Net.Http.HttpMethod]::Get)
            return [pscustomobject]@{ StatusCode=$getResult.StatusCode; Content=$getResult.Content }
        }
        return [pscustomobject]@{ StatusCode=$headResult.StatusCode; Content=$headResult.Content }
    } catch { $creationError = $_ }
      finally { if ($client){$client.Dispose()}; if ($handler){$handler.Dispose()} }

    $sec = [Math]::Ceiling($TimeoutMs/1000.0); if ($sec -lt 1) { $sec = 1 }
    foreach ($fallbackMethod in @('HEAD','GET')) {
        try {
            $args = @{ Uri=$Uri; Method=$fallbackMethod; TimeoutSec=$sec; ErrorAction='Stop' }
            if ($Headers) { $args['Headers'] = $Headers }
            $r = Invoke-WebRequest @args
            $statusCode=[int]$r.StatusCode
            if ($fallbackMethod -eq 'HEAD' -and $statusCode -eq 405) { continue }
            $body=''; if ($r.Content) { $body=$r.Content; if ($body.Length -gt 200){$body=$body.Substring(0,200)} }
            return [pscustomobject]@{ StatusCode=$statusCode; Content=$body }
        } catch { if ($fallbackMethod -eq 'HEAD') { continue }; throw }
    }

    if ($creationError) { throw $creationError }
    throw "No response received from $Uri."
}

function Write-ResponseSnippet { 
    param([string]$Content)
    if ([string]::IsNullOrWhiteSpace($Content)) { return }
    $length  = [Math]::Min(200,$Content.Length)
    $snippet = $Content.Substring(0,$length).Replace("`r",' ').Replace("`n",' ').Trim()
    Write-Host "Response: $snippet" -ForegroundColor DarkGray
}

function Get-PowerShellExecutable {
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwsh) { return $pwsh.Source }
    $winps = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($winps) { return $winps.Source }
    throw 'Neither pwsh nor powershell.exe found in PATH.'
}

function New-TempLogPaths {
    $ts = Get-Date -Format 'yyyyMMdd_HHmmss_ffff'
    @{ Out = Join-Path $env:TEMP ("start-app-out-$ts.log"); Err = Join-Path $env:TEMP ("start-app-err-$ts.log") }
}

function Escape-SingleQuoted { 
    param([Parameter(Mandatory)][string]$Text) 
    $Text -replace "'", "''" 
}

function Invoke-StartApp-WithDiagnostics {
    param([Parameter(Mandatory)][string]$PsExe,[Parameter(Mandatory)][string]$StartApp,[string[]]$Args,[Parameter(Mandatory)][string]$WorkingDirectory)
    $logs = New-TempLogPaths
    $common = @('-NoLogo','-NoProfile','-File',$StartApp); if ($Args) { $common += $Args }
    $argList = ($PsExe -like '*pwsh*') ? $common : @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$StartApp) + $Args
    Write-Host "Launching: $PsExe $($argList -join ' ')" -ForegroundColor DarkGray
    $p = Start-Process -FilePath $PsExe -ArgumentList $argList -WorkingDirectory $WorkingDirectory `
                       -RedirectStandardOutput $($logs.Out) -RedirectStandardError $($logs.Err) -Wait -PassThru
    $outTail = (Get-Content -Path $logs.Out -ErrorAction SilentlyContinue -Tail 200) -join "`n"
    $errTail = (Get-Content -Path $logs.Err -ErrorAction SilentlyContinue -Tail 200) -join "`n"
    $bothEmpty = ([string]::IsNullOrWhiteSpace($outTail) -and [string]::IsNullOrWhiteSpace($errTail))
    if ($p.ExitCode -eq 0 -and -not $bothEmpty) { return @{ ExitCode=0; Out=$outTail; Err=$errTail } }

    $wrapper = Join-Path $env:TEMP ("start-app-wrapper-{0}.ps1" -f (Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
    $qStart  = "'" + (Escape-SingleQuoted -Text $StartApp) + "'"
    $qArgs   = @(); foreach ($a in ($Args | ForEach-Object { $_ })) { $qArgs += ("'" + (Escape-SingleQuoted -Text ([string]$a)) + "'") }
    $wrapperContent = @"
`$ErrorActionPreference = 'Stop'
try {
    & $qStart @($($qArgs -join ',')) 
    `$ec = `$LASTEXITCODE
    if (`$ec -is [int] -and `$ec -ne 0) { throw "Start-App.ps1 set non-zero exit code `$ec." }
    exit 0
}
catch {
    "`$(`$PSItem | Format-List * -Force | Out-String)"
    Write-Error `$PSItem
    exit 1
}
"@
    Set-Content -Path $wrapper -Value $wrapperContent -Encoding UTF8
    $logs2 = New-TempLogPaths
    $argList2 = ($PsExe -like '*pwsh*') ? @('-NoLogo','-NoProfile','-File',$wrapper)
                                        : @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$wrapper)
    Write-Host "Re-launching via wrapper: $PsExe $($argList2 -join ' ')" -ForegroundColor DarkGray
    $p2 = Start-Process -FilePath $PsExe -ArgumentList $argList2 -WorkingDirectory $WorkingDirectory `
                        -RedirectStandardOutput $($logs2.Out) -RedirectStandardError $($logs2.Err) -Wait -PassThru
    try {
        $out2 = (Get-Content -Path $logs2.Out -ErrorAction SilentlyContinue -Tail 500) -join "`n"
        $err2 = (Get-Content -Path $logs2.Err -ErrorAction SilentlyContinue -Tail 500) -join "`n"
    } finally { Remove-Item -Path $wrapper -ErrorAction SilentlyContinue }
    return @{ ExitCode=$p2.ExitCode; Out=$out2; Err=$err2 }
}

$exitCode = 0
Push-Location -Path $repoRoot

try {
    $envFilePath = Join-Path $repoRoot '.env.dev'
    $envValues = Get-SimpleEnvValues -Path $envFilePath
    if (-not $ServiceToken -and $envValues.ContainsKey('import_to_sabt_auth')) {
        try { 
            $authObj = $envValues['import_to_sabt_auth'] | ConvertFrom-Json
            if ($authObj.service_token) { $ServiceToken = "$($authObj.service_token)" } 
        } catch {}
    }
    if (-not $MetricsToken -and $envValues.ContainsKey('import_to_sabt_auth')) {
        try { 
            $authObj = $envValues['import_to_sabt_auth'] | ConvertFrom-Json
            if ($authObj.metrics_token) { $MetricsToken = "$($authObj.metrics_token)" } 
        } catch {}
    }
    if (-not $ServiceToken) { $ServiceToken = 'dev-admin' }
    if (-not $MetricsToken) { $MetricsToken = 'dev-metrics' }

    $baseUri    = $Base.TrimEnd('/')
    $hostUri    = [System.Uri]::new($baseUri)
    $port       = $hostUri.Port
    $targetHost = if ($hostUri.Host) { $hostUri.Host } else { '127.0.0.1' }

    $startAppResolved = if ($StartAppPath) {
        if (Test-Path $StartAppPath) { (Resolve-Path $StartAppPath).Path } else { throw "Start-App.ps1 not found at provided path: $StartAppPath" }
    } else {
        Find-FileUpwards -StartDir $scriptRoot -FileName 'Start-App.ps1' -MaxDepth 3
    }

    if (-not (Test-TcpPortOpen -TargetHost $targetHost -Port $port)) {
        if ($SkipStartApp) { throw "Service is not reachable and -SkipStartApp was specified." }
        Write-Host "Service is not reachable; attempting to run Start-App.ps1" -ForegroundColor Yellow
        if (-not $startAppResolved) { throw "Start-App.ps1 was not found near script root." }

        $psExe = Get-PowerShellExecutable
        $wd    = Split-Path -Parent $startAppResolved
        $run   = Invoke-StartApp-WithDiagnostics -PsExe $psExe -StartApp $startAppResolved -Args $StartAppArgs -WorkingDirectory $wd
        if ($run.ExitCode -ne 0) {
            $msg = "Start-App.ps1 exited with code {0}.`n--- stdout (tail) ---`n{1}`n--- stderr (tail) ---`n{2}" -f $run.ExitCode, $run.Out, $run.Err
            throw $msg
        }

        Start-Sleep -Seconds 2
        if (-not (Test-TcpPortOpen -TargetHost $targetHost -Port $port -TimeoutMs 1000)) {
            throw "Port $port on $targetHost is still closed after Start-App.ps1."
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    $readyUri = "$baseUri/readyz"
    $ready    = $false
    Write-Host "Checking /readyz ..." -ForegroundColor DarkGray
    while ([DateTime]::UtcNow -lt $deadline) {
        try { 
            $r = Invoke-HttpHeadOrGet -Uri $readyUri -TimeoutMs 2000 -Method 'HEAD'
            if ($r.StatusCode -eq 200) { $ready = $true; break } 
        }
        catch { Start-Sleep -Milliseconds 500 }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw "Timeout ($TimeoutSec s) waiting for HTTP 200 from /readyz." }

    $h = Invoke-HttpHeadOrGet -Uri "$baseUri/ui/health" -Headers @{ Authorization = "Bearer $ServiceToken" } -TimeoutMs 3000
    if ($h.StatusCode -ne 200) { 
        Write-ResponseSnippet -Content $h.Content
        throw "/ui/health returned non-200 status (StatusCode=$($h.StatusCode))." 
    }

    $m = Invoke-HttpHeadOrGet -Uri "$baseUri/metrics" -Headers @{ 'X-Metrics-Token' = $MetricsToken } -TimeoutMs 3000
    if ($m.StatusCode -ne 200) { 
        Write-ResponseSnippet -Content $m.Content
        throw "/metrics returned non-200 status (StatusCode=$($m.StatusCode))." 
    }

    Write-Host "Smoke test PASSED" -ForegroundColor Green
}
catch {
    $exitCode = 1
    $e = $PSItem  # استفاده از $PSItem به جای $_
    $msg = if ($e -and $e.Exception) { 
        $e.Exception.Message 
    } elseif ($Error[0]) { 
        $Error[0].Exception.Message 
    } else { 
        'Unknown error occurred' 
    }
    Write-Host "ERROR: Smoke test FAILED: $msg" -ForegroundColor Red
}
finally { 
    Pop-Location
    exit $exitCode
}