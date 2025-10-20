#!/usr/bin/env pwsh
<#!
.SYNOPSIS
    اسکریپت تشخیصی فقط-خواندنی برای بررسی پیش‌نیازهای ویندوزی Student Mentor Allocation.

.NOTES
    پیام‌ها و خروجی‌ها کاملاً قطعی و فارسی هستند. هیچ تغییری در رجیستری یا پیکربندی سیستم داده نمی‌شود.
!>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest

$checks = @()
$status = "ok"

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Message,
        $Details
    )

    $global:checks += [ordered]@{
        name    = $Name
        ok      = $Ok
        message = $Message
        details = $Details
    }

    if (-not $Ok) {
        $global:status = "fail"
    }
}

function Get-GitConfigValue {
    param(
        [string]$Key
    )

    try {
        $value = git config --get $Key 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        return ($value | ForEach-Object { $_.Trim() }) -join ""
    }
    catch {
        return $null
    }
}

# 1) PowerShell version & architecture
$psVersion = $PSVersionTable.PSVersion
$is64Bit = [Environment]::Is64BitProcess
$psOk = ($psVersion.Major -gt 7) -or ($psVersion.Major -eq 7 -and $psVersion.Minor -ge 4)
Add-Check -Name "powershell_version" -Ok:$psOk -Message:(if ($psOk) { "نسخهٔ PowerShell معتبر است." } else { "PowerShell باید حداقل نسخهٔ ۷٫۴ باشد." }) -Details:@{
        version        = $psVersion.ToString()
        is_64bit       = $is64Bit
        required_minor = "7.4"
    }

# 2) Python 3.11 x64 availability
$pyInfo = $null
$pyMessage = "Python 3.11 در دسترس است."
$pyOk = $false
try {
    $pyCommand = Get-Command py -ErrorAction Stop
    $pyJson = & $pyCommand.Source -3.11 -c "import json, platform, sys; print(json.dumps({'version': platform.python_version(), 'arch': platform.architecture()[0], 'is_64bit': sys.maxsize > 2**32}))"
    $pyInfo = $pyJson | ConvertFrom-Json
    if ($pyInfo.version -like '3.11*' -and $pyInfo.arch -eq '64bit' -and $pyInfo.is_64bit) {
        $pyOk = $true
    }
    else {
        $pyMessage = "Python باید نسخهٔ ۳٫۱۱ و ۶۴-بیتی باشد."
    }
}
catch {
    $pyMessage = "Python 3.11 یافت نشد یا قابل اجرا نیست."
}

Add-Check -Name "python311" -Ok:$pyOk -Message:$pyMessage -Details:@{
        version = if ($pyInfo) { $pyInfo.version } else { $null }
        arch    = if ($pyInfo) { $pyInfo.arch } else { $null }
        is_64bit = if ($pyInfo) { [bool]$pyInfo.is_64bit } else { $false }
    }

# 3) pip availability (Python 3.11)
$pipOk = $false
$pipMessage = "pip برای Python 3.11 آماده است."
$pipVersion = $null
if ($pyOk) {
    try {
        $pipOutput = & py -3.11 -m pip --version
        if ($LASTEXITCODE -eq 0 -and $pipOutput) {
            $pipOk = $true
            $pipVersion = ($pipOutput -split '\s+')[1]
        }
        else {
            $pipMessage = "pip برای Python 3.11 به‌درستی گزارش نمی‌دهد."
        }
    }
    catch {
        $pipMessage = "اجرای pip با Python 3.11 موفق نبود."
    }
}
else {
    $pipMessage = "به علت نبود Python 3.11 نمی‌توان pip را بررسی کرد."
}

Add-Check -Name "pip" -Ok:$pipOk -Message:$pipMessage -Details:@{
        version = $pipVersion
    }

# 4) Git availability و تنظیمات CRLF/longpaths
$gitOk = $false
$gitMessage = "Git آماده است."
$gitDetails = @{}
try {
    $gitCommand = Get-Command git -ErrorAction Stop
    $gitVersionRaw = & $gitCommand.Source --version
    if ($LASTEXITCODE -eq 0) {
        $gitOk = $true
        $gitDetails.version = $gitVersionRaw.Trim()
    }
    else {
        $gitMessage = "اجرای Git موفق نبود."
    }
}
catch {
    $gitMessage = "Git یافت نشد یا در مسیر سیستم نیست."
}

$autocrlf = Get-GitConfigValue -Key "core.autocrlf"
$longpaths = Get-GitConfigValue -Key "core.longpaths"
$gitDetails.core_autocrlf = if ($autocrlf) { $autocrlf } else { "(تنظیم نشده)" }
$gitDetails.core_longpaths = if ($longpaths) { $longpaths } else { "(تنظیم نشده)" }

Add-Check -Name "git" -Ok:$gitOk -Message:$gitMessage -Details:$gitDetails

# 5) UTF-8 output encoding
$encodingOk = $false
$encodingMessage = "خروجی PowerShell روی UTF-8 تنظیم است."
$consoleEncoding = [Console]::OutputEncoding.WebName
$outputEncoding = $OutputEncoding.WebName
if ($consoleEncoding -eq 'utf-8' -and $outputEncoding -eq 'utf-8') {
    $encodingOk = $true
}
else {
    $encodingMessage = "برای جلوگیری از مشکلات Excel، خروجی باید UTF-8 باشد."
}

Add-Check -Name "utf8" -Ok:$encodingOk -Message:$encodingMessage -Details:@{
        console = $consoleEncoding
        output  = $outputEncoding
    }

# 6) تحمل قطع اینترنت (اطلاع رسانی)
Add-Check -Name "offline_ready" -Ok:$true -Message:"اجرای اسکریپت به اتصال اینترنت نیاز ندارد." -Details:@{}

$log = [ordered]@{
    correlation_id = "00000000-0000-0000-0000-000000000000"
    timestamp       = "1970-01-01T00:00:00Z"
    status          = $status
    checks          = $checks
}

$log | ConvertTo-Json -Depth 5
