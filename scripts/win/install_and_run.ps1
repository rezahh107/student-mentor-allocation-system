#requires -Version 7.0
<#!
    Self-healing installer/runner for ImportToSabt on Windows 10/11.
    Execute block-by-block in PowerShell 7+; CI can pass switches for headless mode.
!>

[CmdletBinding()]
param(
    [switch] $Ci,
    [switch] $NoDocker,
    [int] $Port = 8000,
    [string] $MetricsToken,
    [string] $RunId
)

chcp 65001 | Out-Null
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Script:CiMode = [bool]$Ci
$Script:CurrentStep = 'init'
$Script:InstallerLog = @()
$Script:ProbeResults = @()
$Script:EnvSnapshot = [ordered]@{}
$Script:CiReportsDir = $null
$Script:TimeoutMultiplier = if ($Script:CiMode) { 0.6 } else { 1.0 }

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = $env:GITHUB_RUN_ID
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = Get-Date -Format 'yyyyMMddHHmmssfff'
}
$sanitizedRunId = ($RunId -replace '[^a-zA-Z0-9\-]', '')
if ([string]::IsNullOrWhiteSpace($sanitizedRunId)) {
    $sanitizedRunId = 'local'
}
$Script:RunId = $sanitizedRunId
$Script:RedisContainerName = "sma-dev-redis-$sanitizedRunId"
$Script:PostgresContainerName = "sma-dev-postgres-$sanitizedRunId"
Write-Result -Status 'PASS' -Message "Run identifier set to $sanitizedRunId" | Out-Null

function Initialize-CiReports {
    if (-not $Script:CiMode) { return }
    $reportsRoot = Join-Path -Path (Get-Location) -ChildPath 'reports/ci'
    if (-not (Test-Path -LiteralPath $reportsRoot)) {
        New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null
    }
    $Script:CiReportsDir = $reportsRoot
}

function Write-CiLog {
    param(
        [Parameter(Mandatory)][string] $Status,
        [Parameter(Mandatory)][string] $Step,
        [Parameter(Mandatory)][string] $Detail
    )

    if (-not $Script:CiMode) { return }
    $entry = [ordered]@{
        timestamp = [DateTime]::UtcNow.ToString('o')
        status    = $Status
        step      = $Step
        detail    = $Detail
    }
    $Script:InstallerLog += $entry
}

function Add-ProbeResult {
    param(
        [Parameter(Mandatory)][string] $Label,
        [Parameter(Mandatory)][int] $StatusCode,
        [string] $Body
    )

    if (-not $Script:CiMode) { return }
    $Script:ProbeResults += [ordered]@{
        label = $Label
        status = $StatusCode
        body = if ($Body -and $Body.Length -gt 200) { $Body.Substring(0, 200) } else { $Body }
    }
}

function Save-CiArtifacts {
    if (-not $Script:CiMode) { return }
    if (-not $Script:CiReportsDir) { return }

    $installerPath = Join-Path $Script:CiReportsDir 'installer.ndjson'
    $Script:InstallerLog | ForEach-Object {
        ($_ | ConvertTo-Json -Depth 4 -Compress)
    } | Set-Content -LiteralPath $installerPath -Encoding UTF8

    $probesPath = Join-Path $Script:CiReportsDir 'probes.json'
    $Script:ProbeResults | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $probesPath -Encoding UTF8

    $envPath = Join-Path $Script:CiReportsDir 'env_dump.json'
    $Script:EnvSnapshot | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $envPath -Encoding UTF8

    $pipFreezePath = Join-Path $Script:CiReportsDir 'pip-freeze.txt'
    try {
        & python -m pip freeze | Set-Content -LiteralPath $pipFreezePath -Encoding UTF8
    }
    catch {
        # ignore; Write-Result already recorded failure if python unavailable
    }
}

function Set-Step {
    param([Parameter(Mandatory)][string] $Name)
    $Script:CurrentStep = $Name
}

function Write-Result {
    param(
        [Parameter(Mandatory)][ValidateSet('PASS','FIXED','SKIP','FAIL')] [string] $Status,
        [Parameter(Mandatory)][string] $Message,
        [string] $Step
    )

    if (-not $Step) { $Step = $Script:CurrentStep }
    $line = "[$Status] $Step::$Message"
    $color = switch ($Status) {
        'PASS'  { 'Green' }
        'FIXED' { 'Yellow' }
        'SKIP'  { 'DarkGray' }
        'FAIL'  { 'Red' }
    }
    Write-CiLog -Status $Status -Step $Step -Detail $Message
    Write-Host $line -ForegroundColor $color
    $global:LASTEXITCODE = if ($Status -eq 'FAIL') { 1 } else { 0 }
    return $Status -ne 'FAIL'
}

function Test-Command {
    param(
        [Parameter(Mandatory)][string] $Name,
        [string] $DisplayName = $Name,
        [switch] $Optional
    )

    try {
        $cmd = Get-Command -Name $Name -ErrorAction Stop
        return Write-Result -Status 'PASS' -Message "Command '$DisplayName' found at $($cmd.Source)"
    }
    catch {
        if ($Optional) {
            return Write-Result -Status 'SKIP' -Message "Command '$DisplayName' not found (optional). $_"
        }
        Write-Result -Status 'FAIL' -Message "Command '$DisplayName' is missing. $_" | Out-Null
        return $false
    }
}

function Test-PortOpen {
    param(
        [Parameter(Mandatory)][string] $Host,
        [Parameter(Mandatory)][int] $Port,
        [int] $TimeoutMs = 800,
        [switch] $InfoOnly,
        [switch] $Silent
    )

    $timeout = [int]([Math]::Round($TimeoutMs * $Script:TimeoutMultiplier))
    if ($timeout -lt 200) { $timeout = 200 }
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect($Host, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($timeout)) {
            if ($Silent) {
                $global:LASTEXITCODE = 1
                return $false
            }
            $status = $InfoOnly ? 'SKIP' : 'FAIL'
            Write-Result -Status $status -Message "Port $Host:$Port closed within ${timeout}ms" | Out-Null
            return $false
        }
        $client.EndConnect($async)
        if (-not $Silent) {
            Write-Result -Status 'PASS' -Message "Port $Host:$Port open" | Out-Null
        }
        else {
            $global:LASTEXITCODE = 0
        }
        return $true
    }
    catch {
        if ($Silent) {
            $global:LASTEXITCODE = 1
            return $false
        }
        $status = $InfoOnly ? 'SKIP' : 'FAIL'
        Write-Result -Status $status -Message "Port $Host:$Port unreachable. $_" | Out-Null
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Invoke-Web {
    param(
        [Parameter(Mandatory)][string] $Uri,
        [string] $Method = 'GET',
        [hashtable] $Headers,
        [int] $ExpectedStatus = 200,
        [string] $Label = $Uri
    )

    try {
        $response = Invoke-WebRequest -Uri $Uri -Method $Method -Headers $Headers -TimeoutSec ([int](10 * $Script:TimeoutMultiplier + 1))
        Add-ProbeResult -Label $Label -StatusCode $response.StatusCode -Body $response.Content
        if ($response.StatusCode -eq $ExpectedStatus) {
            Write-Result -Status 'PASS' -Message "$Label → HTTP $($response.StatusCode)"
            return $true
        }
        $body = $response.Content
        if ($body.Length -gt 100) { $body = $body.Substring(0, 100) }
        Write-Result -Status 'FAIL' -Message "$Label expected $ExpectedStatus but got $($response.StatusCode): $body"
        return $false
    }
    catch {
        Write-Result -Status 'FAIL' -Message "$Label failed. $_"
        Add-ProbeResult -Label $Label -StatusCode 0 -Body ($_.ToString())
        return $false
    }
}

function Ensure-WingetPackage {
    param(
        [Parameter(Mandatory)][string] $Id,
        [string] $Source = 'winget',
        [string] $Override
    )

    $listArgs = @('list', '--exact', '--id', $Id)
    $existing = & winget @listArgs
    if ($LASTEXITCODE -eq 0 -and $existing -match $Id) {
        return Write-Result -Status 'SKIP' -Message "Winget package '$Id' already installed"
    }

    $installArgs = @('install', '--exact', '--id', $Id, '--source', $Source, '--accept-package-agreements', '--accept-source-agreements')
    if ($Override) { $installArgs += @('--override', $Override) }

    try {
        & winget @installArgs
        if ($LASTEXITCODE -eq 0) {
            return Write-Result -Status 'FIXED' -Message "Installed winget package '$Id'"
        }
    }
    catch {
        Write-Result -Status 'FAIL' -Message "Failed installing '$Id'. $_" | Out-Null
        return $false
    }

    Write-Result -Status 'FAIL' -Message "winget returned exit code $LASTEXITCODE for '$Id'" | Out-Null
    return $false
}

function Ensure-DockerContainer {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Image,
        [string[]] $RunArgs
    )

    if ($Script:CiMode -and $Script:NoDockerPreference) {
        Write-Result -Status 'SKIP' -Message "CI NoDocker preference set; container '$Name' skipped"
        return $false
    }

    if ($Script:NoDockerPreference) {
        Write-Result -Status 'SKIP' -Message "NoDocker flag set; container '$Name' skipped"
        return $false
    }

    if (-not (Test-Command -Name 'docker' -DisplayName 'docker' -Optional)) {
        Write-Result -Status 'SKIP' -Message "Docker CLI not available; container '$Name' skipped"
        return $false
    }

    $status = docker ps -a --filter "name=^$Name$" --format '{{.State}}'
    if ($LASTEXITCODE -ne 0) {
        Write-Result -Status 'FAIL' -Message "Failed querying docker for '$Name'"
        return $false
    }

    if ($status) {
        $isRunning = docker inspect -f '{{.State.Running}}' $Name
        if ($LASTEXITCODE -eq 0 -and $isRunning -eq 'true') {
            Write-Result -Status 'PASS' -Message "Docker container '$Name' already running"
            return $true
        }
        docker rm -f $Name | Out-Null
        Write-Result -Status 'FIXED' -Message "Removed stale container '$Name'"
    }

    $args = @('run', '--detach', '--name', $Name) + $RunArgs + @($Image)
    $null = docker @args
    if ($LASTEXITCODE -eq 0) {
        Write-Result -Status 'FIXED' -Message "Started container '$Name' from '$Image'"
        return $true
    }

    Write-Result -Status 'FAIL' -Message "Failed to start docker container '$Name'"
    return $false
}

function Ensure-Var {
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][string] $Key,
        [Parameter(Mandatory)][string] $Value
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Result -Status 'FAIL' -Message "File '$Path' not found for Ensure-Var"
        return $false
    }

    $lines = Get-Content -LiteralPath $Path
    $pattern = "^{0}=.*$" -f [regex]::Escape($Key)
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*#') { continue }
        if ($lines[$i] -match $pattern) {
            $found = $true
            if ($lines[$i] -ne "$Key=$Value") {
                $lines[$i] = "$Key=$Value"
                Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
                Write-Result -Status 'FIXED' -Message "Updated $Key in $(Split-Path -Leaf $Path)"
                return $true
            }
            Write-Result -Status 'PASS' -Message "$Key already set in $(Split-Path -Leaf $Path)"
            return $true
        }
    }

    $lines += "$Key=$Value"
    Set-Content -LiteralPath $Path -Value $lines -Encoding UTF8
    Write-Result -Status 'FIXED' -Message "Added $Key to $(Split-Path -Leaf $Path)"
    return $true
}

function Clear-StaleImportEnv {
    $removed = @()
    Get-ChildItem Env: | Where-Object { $_.Name -like 'IMPORT_TO_SABT_*' } | ForEach-Object {
        $removed += $_.Name
        Remove-Item -LiteralPath "Env:$($_.Name)" -Force
    }

    if ($removed.Count -gt 0) {
        Write-Result -Status 'FIXED' -Message "Cleared stale process env vars: $($removed -join ', ')"
    }
    else {
        Write-Result -Status 'PASS' -Message 'No IMPORT_TO_SABT_* process env vars to clear'
    }
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][string] $Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $pattern = "^{0}=(.*)$" -f [regex]::Escape($Key)
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#') { continue }
        if ($line -match $pattern) {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Snapshot-EnvValue {
    param(
        [Parameter(Mandatory)][string] $Key,
        [Parameter()][string] $Value
    )
    if (-not $Script:CiMode) { return }
    $Script:EnvSnapshot[$Key] = $Value
}

Initialize-CiReports
$Script:NoDockerPreference = $NoDocker.IsPresent
Snapshot-EnvValue -Key 'RUN_ID' -Value $Script:RunId

Set-Step 'repo-root'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptRoot '..\..')).Path
Set-Location -Path $repoRoot
Write-Result -Status 'PASS' -Message "Repository root set to $repoRoot" | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'pyproject.toml'))) {
    Write-Result -Status 'FAIL' -Message 'pyproject.toml not found; run this script from repository root'
    Save-CiArtifacts
    exit 1
}

Set-Step 'execution-policy'
$currentPolicy = Get-ExecutionPolicy -Scope CurrentUser -ErrorAction SilentlyContinue
if ($currentPolicy -ne 'RemoteSigned') {
    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
    Write-Result -Status 'FIXED' -Message 'ExecutionPolicy set to RemoteSigned (CurrentUser)' | Out-Null
}
else {
    Write-Result -Status 'PASS' -Message 'ExecutionPolicy already RemoteSigned (CurrentUser)' | Out-Null
}

Set-Step 'prerequisites'
if (-not (Test-Command -Name 'winget')) {
    Write-Result -Status 'FAIL' -Message 'winget is required; install from Microsoft Store first.'
    Save-CiArtifacts
    exit 1
}

if (-not (Ensure-WingetPackage -Id 'Microsoft.VisualStudio.2022.BuildTools' -Override '--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools')) {
    Save-CiArtifacts
    exit 1
}

Set-Step 'python-discovery'
$pythonExe = $null
$pythonBaseArgs = @()
$pythonDisplay = 'python'
if (Test-Command -Name 'py' -DisplayName 'py launcher' -Optional) {
    try {
        $versionOutput = & py -3.11 --version
        if ($LASTEXITCODE -eq 0 -and $versionOutput -match 'Python 3\.11\.([0-9]+)') {
            $minor = [int]$Matches[1]
            if ($minor -eq 12) {
                $pythonExe = 'py'
                $pythonBaseArgs = @('-3.11')
                $pythonDisplay = 'py -3.11'
                Write-Result -Status 'PASS' -Message "Using Python from py launcher: $versionOutput" | Out-Null
            }
        }
    }
    catch {
        Write-Result -Status 'SKIP' -Message "py launcher failed for 3.11; will try other interpreters. $_" | Out-Null
    }
}

if (-not $pythonExe) {
    $pyenvCandidate = Join-Path $Env:USERPROFILE '.pyenv/pyenv-win/versions/3.11.12/python.exe'
    if (Test-Path -LiteralPath $pyenvCandidate) {
        $pythonExe = $pyenvCandidate
        $pythonBaseArgs = @()
        $pythonDisplay = $pyenvCandidate
        Write-Result -Status 'PASS' -Message "Using pyenv-win interpreter: $pyenvCandidate" | Out-Null
    }
}

if (-not $pythonExe -and (Test-Command -Name 'python' -DisplayName 'python.exe' -Optional)) {
    $pythonVersion = & python --version
    if ($LASTEXITCODE -eq 0 -and $pythonVersion -match 'Python 3\.11\.([0-9]+)') {
        $minor = [int]$Matches[1]
        if ($minor -eq 12) {
            $pythonExe = 'python'
            $pythonBaseArgs = @()
            $pythonDisplay = 'python'
            Write-Result -Status 'PASS' -Message "Using python.exe: $pythonVersion" | Out-Null
        }
    }
}

if (-not $pythonExe) {
    Write-Result -Status 'FAIL' -Message 'Python 3.11.12 is required. Install it with "winget install --id Python.Python.3.11".'
    Save-CiArtifacts
    exit 1
}

$pythonVersionCheck = & $pythonExe @($pythonBaseArgs + @('--version'))
if ($LASTEXITCODE -ne 0 -or ($pythonVersionCheck -notmatch 'Python 3\.11\.12')) {
    Write-Result -Status 'FAIL' -Message "Expected Python 3.11.12 but got '$pythonVersionCheck'"
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message "$pythonDisplay version check OK ($pythonVersionCheck)" | Out-Null

Set-Step 'venv'
$venvPath = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $pythonExe @($pythonBaseArgs + @('-m','venv',$venvPath))
    Write-Result -Status 'FIXED' -Message 'Created .venv with Python 3.11.12' | Out-Null
}
else {
    Write-Result -Status 'PASS' -Message '.venv already exists' | Out-Null
}

$activateScript = Join-Path $venvPath 'Scripts/Activate.ps1'
if (-not (Test-Path -LiteralPath $activateScript)) {
    Write-Result -Status 'FAIL' -Message 'Virtual environment activation script missing'
    Save-CiArtifacts
    exit 1
}

. $activateScript
Write-Result -Status 'PASS' -Message "Activated virtual environment at $venvPath" | Out-Null

Set-Step 'pip-install'
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Result -Status 'FAIL' -Message 'pip upgrade failed'
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message 'pip upgraded successfully' | Out-Null

python -m pip install -e .[dev]
if ($LASTEXITCODE -ne 0) {
    Write-Result -Status 'FAIL' -Message 'pip install -e .[dev] failed'
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message 'Editable install with dev extras completed' | Out-Null

python -m pip show uvloop > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    python -m pip uninstall -y uvloop
    if ($LASTEXITCODE -eq 0) {
        Write-Result -Status 'FIXED' -Message 'Removed uvloop (unsupported on Windows)' | Out-Null
    }
    else {
        Write-Result -Status 'FAIL' -Message 'Failed to uninstall uvloop'
        Save-CiArtifacts
        exit 1
    }
}
else {
    Write-Result -Status 'SKIP' -Message 'uvloop not installed' | Out-Null
}

python - <<'PY'
import importlib
import sys
for name in ("sma", "jinja2"):
    try:
        importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"FAIL:{name}:{exc}")
        sys.exit(1)
print("PASS:imports")
PY
if ($LASTEXITCODE -ne 0) {
    Write-Result -Status 'FAIL' -Message 'Import validation failed'
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message 'Core modules (sma, jinja2) import successfully' | Out-Null

python -m pip check
if ($LASTEXITCODE -ne 0) {
    Write-Result -Status 'FAIL' -Message 'pip check failed'
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message 'pip check reports no dependency issues' | Out-Null

Set-Step 'dotenv'
$envPath = Join-Path $repoRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot '.env.example') -Destination $envPath
    Write-Result -Status 'FIXED' -Message 'Created .env from .env.example' | Out-Null
}
else {
    Write-Result -Status 'PASS' -Message '.env already exists' | Out-Null
}

Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_REDIS__DSN' -Value 'redis://127.0.0.1:6379/0' | Out-Null
Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_DATABASE__DSN' -Value 'postgresql+psycopg://postgres:postgres@127.0.0.1:5432/student_mentor' | Out-Null
if ($MetricsToken) {
    Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_AUTH__METRICS_TOKEN' -Value $MetricsToken | Out-Null
}
else {
    Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_AUTH__METRICS_TOKEN' -Value 'dev-metrics-token' | Out-Null
}
Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_AUTH__SERVICE_TOKEN' -Value 'dev-service-token' | Out-Null
Ensure-Var -Path $envPath -Key 'IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS' -Value 'true' | Out-Null

Clear-StaleImportEnv

python - <<'PY'
from sma.phase6_import_to_sabt.app.config import AppConfig
AppConfig()
PY
if ($LASTEXITCODE -ne 0) {
    Write-Result -Status 'FAIL' -Message 'AppConfig validation failed. Check .env entries.'
    Save-CiArtifacts
    exit 1
}
Write-Result -Status 'PASS' -Message 'AppConfig instantiated successfully' | Out-Null

$environmentValue = Get-DotEnvValue -Path $envPath -Key 'ENVIRONMENT'
$publicDocsValue = Get-DotEnvValue -Path $envPath -Key 'IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS'
$publicDocsEnabled = $false
if ($publicDocsValue) {
    $publicDocsEnabled = $publicDocsValue.Trim().ToLower() -in @('1','true','yes','on')
}
if (($environmentValue) -and ($environmentValue.Trim().ToLower() -eq 'production') -and $publicDocsEnabled) {
    Write-Result -Status 'FAIL' -Message 'ENVIRONMENT=production cannot use PUBLIC_DOCS=true. اسناد عمومی در تولید مجاز نیست.'
    Save-CiArtifacts
    exit 1
}

Snapshot-EnvValue -Key 'ENVIRONMENT' -Value $environmentValue
Snapshot-EnvValue -Key 'IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS' -Value $publicDocsValue
Snapshot-EnvValue -Key 'DEVMODE' -Value $Env:DEVMODE

Set-Step 'services'
$dockerAvailable = $false
if (-not $Script:NoDockerPreference) {
    $dockerAvailable = Test-Command -Name 'docker' -DisplayName 'docker CLI' -Optional
}
else {
    $null = Write-Result -Status 'SKIP' -Message 'Docker forced off via -NoDocker'
}

if (-not $dockerAvailable) {
    $Env:DEVMODE = '1'
    Snapshot-EnvValue -Key 'DEVMODE' -Value $Env:DEVMODE
    Write-Result -Status 'FIXED' -Message 'Docker unavailable → set DEVMODE=1 for fakeredis/SQLite fallback' | Out-Null
}

$redisOpen = Test-PortOpen -Host '127.0.0.1' -Port 6379 -InfoOnly
if (-not $redisOpen -and $dockerAvailable) {
    Ensure-DockerContainer -Name $Script:RedisContainerName -Image 'redis:7' -RunArgs @('--restart','unless-stopped','-p','6379:6379') | Out-Null
    for ($attempt=0; $attempt -lt 10; $attempt++) {
        $delay = [Math]::Min(5000, [Math]::Pow(2, $attempt) * 100) * $Script:TimeoutMultiplier
        Start-Sleep -Milliseconds ([int][Math]::Max(150, $delay))
        if (Test-PortOpen -Host '127.0.0.1' -Port 6379 -Silent) { break }
    }
    if (-not (Test-PortOpen -Host '127.0.0.1' -Port 6379)) {
        Write-Result -Status 'FAIL' -Message 'Redis port 6379 still closed after provisioning'
        Save-CiArtifacts
        exit 1
    }
}

$postgresOpen = Test-PortOpen -Host '127.0.0.1' -Port 5432 -InfoOnly
if (-not $postgresOpen -and $dockerAvailable) {
    Ensure-DockerContainer -Name $Script:PostgresContainerName -Image 'postgres:16' -RunArgs @('--restart','unless-stopped','-e','POSTGRES_PASSWORD=postgres','-e','POSTGRES_DB=student_mentor','-p','5432:5432') | Out-Null
    for ($attempt=0; $attempt -lt 10; $attempt++) {
        $delay = [Math]::Min(5000, [Math]::Pow(2, $attempt) * 100) * $Script:TimeoutMultiplier
        Start-Sleep -Milliseconds ([int][Math]::Max(150, $delay))
        if (Test-PortOpen -Host '127.0.0.1' -Port 5432 -Silent) { break }
    }
    if (-not (Test-PortOpen -Host '127.0.0.1' -Port 5432)) {
        Write-Result -Status 'FAIL' -Message 'PostgreSQL port 5432 still closed after provisioning'
        Save-CiArtifacts
        exit 1
    }
}

if (-not $dockerAvailable -and (-not (Test-PortOpen -Host '127.0.0.1' -Port 6379 -Silent))) {
    Write-Result -Status 'SKIP' -Message 'Redis port closed but Docker unavailable; rely on DEVMODE fakeredis'
}
if (-not $dockerAvailable -and (-not (Test-PortOpen -Host '127.0.0.1' -Port 5432 -Silent))) {
    Write-Result -Status 'SKIP' -Message 'PostgreSQL port closed but Docker unavailable; rely on DEVMODE SQLite fallback'
}

Set-Step 'uvicorn'
$logDir = Join-Path $repoRoot 'tmp\win-run'
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logPath = Join-Path $logDir 'uvicorn.log'
$pythonExecForRun = Join-Path $venvPath 'Scripts/python.exe'
$uvicornArgs = @('-m','uvicorn','main:app','--host','127.0.0.1','--port',$Port.ToString(),'--factory')

$job = Start-Job -ScriptBlock {
    param($Exe, $Args, $WorkingDir, $Log)
    Set-Location -Path $WorkingDir
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = [string]::Join(' ', $Args)
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $process.Start() | Out-Null
    $stdOut = $process.StandardOutput.ReadToEndAsync()
    $stdErr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $output = ($stdOut.Result + "`n" + $stdErr.Result)
    Set-Content -LiteralPath $Log -Value $output -Encoding UTF8
    return @{ ExitCode = $process.ExitCode }
} -ArgumentList @($pythonExecForRun, $uvicornArgs, $repoRoot, $logPath)

Write-Result -Status 'PASS' -Message "Uvicorn job started (Id=$($job.Id))" | Out-Null

$maxWaitMs = [int](12000 * $Script:TimeoutMultiplier)
if ($maxWaitMs -lt 4000) { $maxWaitMs = 4000 }
$start = Get-Date
while (-not (Test-PortOpen -Host '127.0.0.1' -Port $Port -Silent)) {
    Start-Sleep -Milliseconds ([int](400 * $Script:TimeoutMultiplier))
    if ((Get-Date) - $start -ge [TimeSpan]::FromMilliseconds($maxWaitMs)) {
        Write-Result -Status 'FAIL' -Message "Uvicorn did not open port $Port in time"
        if ($job -and ($job.State -eq 'Running')) { Stop-Job -Job $job -Force }
        Save-CiArtifacts
        exit 1
    }
}
Write-Result -Status 'PASS' -Message "Uvicorn listening on port $Port" | Out-Null

Set-Step 'probes'
$baseUrl = "http://127.0.0.1:$Port"
$readyEndpoints = @('/readyz','/healthz','/health')
$readySuccess = $false
foreach ($suffix in $readyEndpoints) {
    if (Invoke-Web -Uri "$baseUrl$suffix" -Label $suffix -ExpectedStatus 200) {
        $readySuccess = $true
        break
    }
}
if (-not $readySuccess) {
    Write-Result -Status 'FAIL' -Message 'No readiness endpoint succeeded'
    if ($job -and ($job.State -eq 'Running')) { Stop-Job -Job $job -Force }
    Save-CiArtifacts
    exit 1
}

if ($publicDocsEnabled) {
    Invoke-Web -Uri "$baseUrl/docs" -Label '/docs' -ExpectedStatus 200 | Out-Null
}
else {
    Invoke-Web -Uri "$baseUrl/docs" -Label '/docs (expected 401/403)' -ExpectedStatus 401 | Out-Null
}

Invoke-Web -Uri "$baseUrl/metrics" -Label '/metrics (no token)' -ExpectedStatus 403 | Out-Null
$metricsTokenValue = Get-DotEnvValue -Path $envPath -Key 'IMPORT_TO_SABT_AUTH__METRICS_TOKEN'
if (-not $metricsTokenValue) {
    Write-Result -Status 'FAIL' -Message 'IMPORT_TO_SABT_AUTH__METRICS_TOKEN missing; cannot probe /metrics'
    if ($job -and ($job.State -eq 'Running')) { Stop-Job -Job $job -Force }
    Save-CiArtifacts
    exit 1
}
Invoke-Web -Uri "$baseUrl/metrics" -Label '/metrics (with token)' -ExpectedStatus 200 -Headers @{ 'Authorization' = "Bearer $metricsTokenValue" } | Out-Null
Snapshot-EnvValue -Key 'IMPORT_TO_SABT_AUTH__METRICS_TOKEN' -Value $metricsTokenValue

if ($job) {
    if ($job.State -eq 'Running') {
        Stop-Job -Job $job -Force
    }
    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force
    if ($result -is [System.Collections.IDictionary] -and $result['ExitCode'] -ne 0) {
        Write-Result -Status 'FAIL' -Message "Uvicorn exited with code $($result['ExitCode'])"
        Save-CiArtifacts
        exit 1
    }
    Write-Result -Status 'PASS' -Message 'Uvicorn job stopped'
}

Save-CiArtifacts
Set-Step 'summary'
Write-Result -Status 'PASS' -Message 'All validations completed successfully' | Out-Null
exit 0
