 [CmdletBinding()]
 param(
     [string]$OutputExamplePath = '.env.example.win',
     [string]$OutputEnvPath = '.env',
     [switch]$WriteEnv,
     [switch]$Force
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

 function Write-AtomicFile {
     <# Evidence: AGENTS.md::6 Atomic I/O; Evidence: AGENTS.md::10 User-Visible Errors #>
     param(
         [Parameter(Mandatory)][string]$Path,
         [Parameter(Mandatory)][string[]]$Content
     )

     $directory = Split-Path -Parent $Path
     if (-not [string]::IsNullOrWhiteSpace($directory) -and -not (Test-Path $directory)) {
         New-Item -ItemType Directory -Force -Path $directory | Out-Null
     }

     $tempPath = "$Path.part"
     $encoding = [System.Text.UTF8Encoding]::new($false)
     $fileStream = [System.IO.FileStream]::new(
         $tempPath,
         [System.IO.FileMode]::Create,
         [System.IO.FileAccess]::Write,
         [System.IO.FileShare]::None
     )
     try {
         $writer = [System.IO.StreamWriter]::new($fileStream, $encoding)
         try {
             foreach ($line in $Content) {
                 $writer.WriteLine($line)
             }
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

 function Convert-ToStringValue {
     param([object]$Value)
     if ($null -eq $Value) { return '' }
     if ($Value -is [bool]) {
         return ([string]$Value).ToLowerInvariant()
     }
     return [string]$Value
 }

 $python = Resolve-Python

 $code = @'
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from sma._local_tools import cli as cli_module
from sma.phase6_import_to_sabt.app.config import AppConfig

ENV_PREFIX = AppConfig.model_config.get("env_prefix", "")


def _normalize(parts: list[str]) -> str:
    return "__".join(part.upper() for part in parts)


def _default_for(field: Any) -> Any:
    if field.default is not PydanticUndefined:
        value = field.default
    elif field.default_factory is not None:
        value = field.default_factory()
    else:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _walk(model: type[BaseModel], parts: list[str], entries: list[dict[str, Any]]) -> None:
    for name, field in model.model_fields.items():
        alias = field.alias or name
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            _walk(annotation, parts + [alias], entries)
            continue
        env_key = ENV_PREFIX + _normalize(parts + [alias])
        entries.append(
            {
                "key": env_key,
                "required": field.is_required(),
                "default": _default_for(field),
            }
        )


def _recommended_values() -> dict[str, str]:
    tokens = cli_module.DEFAULT_TOKENS
    keys = cli_module.DEFAULT_KEYS
    storage = (Path("storage") / "exports").as_posix().replace("/", "\\")
    return {
        "IMPORT_TO_SABT_REDIS__DSN": "redis://localhost:6379/0",
        "IMPORT_TO_SABT_DATABASE__DSN": "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        "IMPORT_TO_SABT_AUTH__SERVICE_TOKEN": tokens[0]["value"],
        "IMPORT_TO_SABT_REDIS__NAMESPACE": "import_to_sabt",
        "IMPORT_TO_SABT_OBSERVABILITY__SERVICE_NAME": "import-to-sabt",
        "IMPORT_TO_SABT_OBSERVABILITY__METRICS_NAMESPACE": "import_to_sabt",
        "EXPORT_STORAGE_DIR": storage,
        "TOKENS": json.dumps(tokens, ensure_ascii=False),
        "DOWNLOAD_SIGNING_KEYS": json.dumps(keys, ensure_ascii=False),
        "METRICS_ENDPOINT_ENABLED": "true",
        "IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS": "true",
    }


def gather() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    _walk(AppConfig, [], entries)
    recommended = _recommended_values()
    return {
        "entries": entries,
        "recommended": recommended,
    }


print(json.dumps(gather(), ensure_ascii=False))
'@

 function Invoke-Main {
     param()

     $resultJson = & $python -c $code
     if ($LASTEXITCODE -ne 0) {
         throw 'خواندن تنظیمات شکست خورد.'
     }

     $result = $resultJson | ConvertFrom-Json
     $entries = @($result.entries)
     if (-not $entries -or $entries.Count -eq 0) {
         throw 'هیچ کلید تنظیماتی یافت نشد.'
     }

     $recommended = @{}
     foreach ($pair in $result.recommended.PSObject.Properties) {
         $recommended[$pair.Name] = [string]$pair.Value
     }

     $map = [ordered]@{}
     foreach ($entry in $entries) {
         $map[$entry.key] = $entry
     }
     foreach ($extraKey in $recommended.Keys) {
         if (-not $map.Contains($extraKey)) {
             $map[$extraKey] = [pscustomobject]@{ key = $extraKey; required = $false; default = $null }
         }
     }

     $header = '# Generated by scripts/win/20-create-env.ps1 (UTF-8, LF)'
     $lines = [System.Collections.Generic.List[string]]::new()
     $lines.Add($header) | Out-Null

     $requiredCount = 0
     foreach ($key in ($map.Keys | Sort-Object)) {
         $entry = $map[$key]
         if ($entry.required) { $requiredCount++ }
         $candidate = $null
         if ($recommended.ContainsKey($key)) {
             $candidate = $recommended[$key]
         } elseif ($entry.default -ne $null -and $entry.default -ne '') {
             $candidate = Convert-ToStringValue -Value $entry.default
         } else {
             $candidate = ''
         }
         $lines.Add("$key=$candidate") | Out-Null
     }

     if ((Test-Path $OutputExamplePath) -and -not $Force) {
         throw "$OutputExamplePath از قبل وجود دارد؛ از -Force استفاده کنید."
     }
     Write-AtomicFile -Path $OutputExamplePath -Content $lines.ToArray()

     if ($WriteEnv) {
         if ((Test-Path $OutputEnvPath) -and -not $Force) {
             throw "$OutputEnvPath از قبل وجود دارد؛ از -Force استفاده کنید."
         }
         Write-AtomicFile -Path $OutputEnvPath -Content $lines.ToArray()
     }

     $totalKeys = $lines.Count - 1
     $optionalKeys = $totalKeys - $requiredCount
     Write-Host "فایل نمونهٔ محیطی ساخته شد: $OutputExamplePath" -ForegroundColor Green
     if ($WriteEnv) {
         Write-Host "فایل .env ایجاد شد." -ForegroundColor Green
     }
     Write-Host ("خلاصهٔ متغیرها: کلیدها={0} (الزامی={1}، اختیاری={2})." -f $totalKeys, $requiredCount, $optionalKeys)
 }

 try {
     Invoke-Main
 } catch {
     Write-Error "ایجاد فایل‌های محیطی ناموفق بود: $($_.Exception.Message)"
     exit 2
 }
