[CmdletBinding()]
param(
    [string]$Host = '127.0.0.1',
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$Background,
    [string]$StateDir = 'tmp\win-app',
    [string[]]$ExtraArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Resolve-Python {
    $venvRoot = Join-Path (Get-Location) '.venv'
    $venvPython = Join-Path $venvRoot 'Scripts/python.exe'
    if (Test-Path $venvPython) {
        return (Resolve-Path $venvPython).Path
    }
    try {
        return (Get-Command py -ErrorAction Stop).Source
    } catch {
        return (Get-Command python -ErrorAction Stop).Source
    }
}

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return @{} }
    $pairs = @{}
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#')) { continue }
        $index = $text.IndexOf('=')
        if ($index -lt 1) { continue }
        $key = $text.Substring(0,$index).Trim()
        $value = $text.Substring($index+1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
            $value = $value.Substring(1,$value.Length-2)
        }
        $pairs[$key] = $value
        [System.Environment]::SetEnvironmentVariable($key,$value)
    }
    return $pairs
}

function New-AtomicFile {
    param([string]$Path,[string]$Content)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $tmp = "$Path.part"
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Content)
    [System.IO.File]::WriteAllBytes($tmp,$bytes)
    $fs = [System.IO.File]::Open($tmp,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
    try { $fs.Flush($true) } finally { $fs.Dispose() }
    Move-Item -Force -Path $tmp -Destination $Path
}

function Wait-ServiceReady {
    param([string]$Url,[int]$MaxAttempts = 20)
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
            try {
                $response = $client.GetAsync($Url).GetAwaiter().GetResult()
                if ($response.IsSuccessStatusCode) {
                    Write-Host "✅ سرویس آماده است: $Url"
                    return
                }
            } catch {
                # retry silently
            }
            $delay = [Math]::Min(3.0,[Math]::Pow(2,$attempt) * 0.1) + (Get-Random -Minimum 0 -Maximum 200)/1000.0
            Write-Host "⏳ انتظار برای آماده‌شدن $Url (تلاش $attempt)" -ForegroundColor Yellow
            Start-Sleep -Seconds $delay
        }
    } finally {
        $client.Dispose()
        $handler.Dispose()
    }
    throw "سرویس در بازهٔ زمانی تعیین‌شده آماده نشد: $Url"
}

$python = Resolve-Python
$envData = Import-DotEnv -Path '.env'

$arguments = @('-m','uvicorn','main:app','--host',$Host,'--port',$Port.ToString())
if ($Reload) { $arguments += '--reload' }
if ($ExtraArgs) { $arguments += $ExtraArgs }

if (-not $Background) {
    Write-Host ("🚀 اجرای uvicorn با فرمان: {0} {1}" -f $python,($arguments -join ' '))
    & $python @arguments
    return
}

$stateDirectory = (New-Item -ItemType Directory -Force -Path $StateDir).FullName
$stdoutPath = Join-Path $stateDirectory 'stdout.log'
$stderrPath = Join-Path $stateDirectory 'stderr.log'

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory (Get-Location) -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
Start-Sleep -Seconds 0.5
$baseUrl = "http://$Host:$Port/readyz"
Wait-ServiceReady -Url $baseUrl

$state = @{ pid = $process.Id; host = $Host; port = $Port; started_at = [DateTimeOffset]::UtcNow.ToString('o'); stdout = $stdoutPath; stderr = $stderrPath }
$stateJson = ($state | ConvertTo-Json -Depth 4)
$stateFile = Join-Path $stateDirectory 'state.json'
New-AtomicFile -Path $stateFile -Content $stateJson
Write-Host "✅ سرور در پس‌زمینه اجرا شد (PID=$($process.Id))" -ForegroundColor Green
