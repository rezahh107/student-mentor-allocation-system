Param(

  [string]$BaseUrl = "http://127.0.0.1:8000",

  [string]$MetricsToken = $env:METRICS_TOKEN,

  [string]$RequirePublicDocs = $env:REQUIRE_PUBLIC_DOCS,

  [string]$OutputJsonPath = "server_check_result.json",

  [string]$OutputLogPath = "run_server_check.log"

)

$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [Text.Encoding]::UTF8

if (Get-Command chcp -ErrorAction SilentlyContinue) { chcp 65001 | Out-Null }



$HttpClient = [System.Net.Http.HttpClient]::new()

$HttpClient.Timeout = [TimeSpan]::FromSeconds(5)

$ProbeEntries = New-Object System.Collections.Generic.List[pscustomobject]

$LogLines = New-Object System.Collections.Generic.List[string]



function Write-LoggedLine {

  param([string]$Message, [string]$Color = $null)

  $LogLines.Add($Message)

  if ($null -ne $Color) {

    Write-Host $Message -ForegroundColor $Color

  } else {

    Write-Host $Message

  }

}



function Ok($m){ Write-LoggedLine "✅ $m" "Green" }

function Warn($m){ Write-LoggedLine "⚠️  $m" "Yellow" }

function Fail($m){ Write-LoggedLine "❌ $m" "Red" }



function Invoke-Endpoint {

  param(

    [string]$Path,

    [int[]]$ExpectedCodes,

    [hashtable]$Headers = @{}

  )

  $attempts = 3

  $backoffMs = 300

  $lastError = $null

  for ($i = 0; $i -lt $attempts; $i++) {

    $code = $null

    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, "$BaseUrl$Path")

    try {

      foreach ($key in $Headers.Keys) {

        $request.Headers.TryAddWithoutValidation($key, $Headers[$key]) | Out-Null

      }

      $response = $HttpClient.SendAsync($request).GetAwaiter().GetResult()

      $code = [int]$response.StatusCode

    } catch {

      $lastError = $_.Exception

      if ($lastError -and $lastError.Response -and $lastError.Response.StatusCode) {

        $code = $lastError.Response.StatusCode.value__

      }

    } finally {

      $request.Dispose()

    }

    $ok = ($code -ne $null) -and ($ExpectedCodes -contains $code)

    $statusLine = $(if ($ok) { "✅" } else { "❌" }) + " $Path -> $code"

    Write-LoggedLine $statusLine $(if ($ok) { "Green" } else { "Red" })

    if ($ok) {

      $ProbeEntries.Add([pscustomobject]@{

        path = $Path

        attempts = $i + 1

        status_code = $code

        expected = $ExpectedCodes

        success = $true

        headers = if ($Headers.Count -gt 0) { @($Headers.GetEnumerator() | ForEach-Object { [pscustomobject]@{ key = $_.Key; value = $_.Value } }) } else { @() }

      })

      return $true

    }

    Start-Sleep -Milliseconds $backoffMs

  }

  if ($lastError) {

    Fail "$Path error: $($lastError.Message)"

  }

  $ProbeEntries.Add([pscustomobject]@{

    path = $Path

    attempts = $attempts

    status_code = $code

    expected = $ExpectedCodes

    success = $false

    error = if ($lastError) { $lastError.Message } else { "unknown" }

    headers = if ($Headers.Count -gt 0) { @($Headers.GetEnumerator() | ForEach-Object { [pscustomobject]@{ key = $_.Key; value = $_.Value } }) } else { @() }

  })

  return $false

}



$pass = 0; $fail = 0

$requireDocs = $false

if (-not [string]::IsNullOrWhiteSpace($RequirePublicDocs)) {

  switch -Regex ($RequirePublicDocs.Trim().ToLowerInvariant()) {

    '^(1|true|yes)$' { $requireDocs = $true }

  }

}



Write-LoggedLine "`n🔍 Running server checks against $BaseUrl" "Cyan"



if (Invoke-Endpoint "/healthz" @(200)) { $pass++ } else { $fail++ }

if (Invoke-Endpoint "/readyz" @(200,503)) { $pass++ } else { $fail++ }



$docExpected = if ($requireDocs) { @(200) } else { @(200,401,403) }

foreach ($p in @("/openapi.json","/docs","/redoc")) {

  if (Invoke-Endpoint $p $docExpected) { $pass++ } else { $fail++ }

}



if (Invoke-Endpoint "/metrics" @(403)) { $pass++ } else { $fail++ }



if ([string]::IsNullOrWhiteSpace($MetricsToken)) {

  Warn "METRICS_TOKEN not set; treating authorized metrics check as N/A"

  $ProbeEntries.Add([pscustomobject]@{

    path = "/metrics"

    attempts = 0

    status_code = $null

    expected = @(200)

    success = $true

    skipped = $true

    headers = @()

  })

  $pass++

} else {

  $headers = @{ Authorization = "Bearer $MetricsToken" }

  if (Invoke-Endpoint "/metrics" @(200) $headers) { $pass++ } else { $fail++ }

}



Write-LoggedLine "`n📊 Result: $pass passed, $fail failed" "Cyan"



$summary = [pscustomobject]@{

  base_url = $BaseUrl

  require_public_docs = $requireDocs

  metrics_token_supplied = -not [string]::IsNullOrWhiteSpace($MetricsToken)

  passed = $pass

  failed = $fail

  checks = $ProbeEntries

}



$LogLines | Set-Content -Path $OutputLogPath -Encoding UTF8

$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputJsonPath -Encoding UTF8



if ($fail -gt 0) {

  $HttpClient.Dispose(); exit 1

} else {

  $HttpClient.Dispose(); exit 0

}

