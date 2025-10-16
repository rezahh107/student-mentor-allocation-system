#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Message,
    [switch]$AutoPush = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-StepBanner {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )

    Write-Host ''
    Write-Host ("════ {0} ════" -f $Title) -ForegroundColor Cyan
}

function Exit-WithHint {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Code,
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [string]$Hint
    )

    Write-Error $Message
    if (-not [string]::IsNullOrWhiteSpace($Hint)) {
        Write-Host $Hint -ForegroundColor Yellow
    }

    exit $Code
}

try {
    if ([string]::IsNullOrWhiteSpace($Message)) {
        Exit-WithHint -Code 1 -Message 'پیام کامیت نمی‌تواند خالی باشد.' -Hint 'یک توضیح معنی‌دار برای تغییرات خود فراهم کنید.'
    }

    $trimmedMessage = $Message.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmedMessage)) {
        Exit-WithHint -Code 1 -Message 'پس از حذف فاصله‌ها، پیام کامیت خالی است.' -Hint 'لطفاً پیام دقیق‌تری برای git commit فراهم کنید.'
    }

    [int]$testsCount = 0
    [int]$lintCount = 0
    [int]$secretsCount = 0
    [string]$remoteUrl = ''
    [string]$currentBranch = ''
    [bool]$autoPushEnabled = $true

    if ($PSBoundParameters.ContainsKey('AutoPush')) {
        $autoPushEnabled = $AutoPush.IsPresent
    }

    Write-StepBanner -Title 'مرحله ۰: آماده‌سازی و شناسایی مخزن'

    $repoRootLines = & git rev-parse --show-toplevel 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($repoRootLines -join [Environment]::NewLine)
        Exit-WithHint -Code 1 -Message "مخزن گیت یافت نشد: $joined" -Hint 'اسکریپت را در ریشهٔ مخزن گیت اجرا کنید.'
    }

    $repoRoot = ($repoRootLines | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($repoRoot)) {
        Exit-WithHint -Code 1 -Message 'git rev-parse مقدار معتبری برنگرداند.' -Hint 'بررسی کنید مخزن به‌درستی مقداردهی شده باشد.'
    }

    Set-Location -Path $repoRoot

    $branchLines = & git rev-parse --abbrev-ref HEAD 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($branchLines -join [Environment]::NewLine)
        Exit-WithHint -Code 1 -Message "شاخهٔ جاری مشخص نشد: $joined" -Hint 'از سلامت مخزن اطمینان حاصل کنید.'
    }

    $currentBranch = ($branchLines | Select-Object -First 1).Trim()
    Write-Host ("شاخهٔ جاری: {0}" -f $currentBranch) -ForegroundColor DarkCyan

    $remoteUrlLines = & git remote get-url origin 2>&1
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 7 -Message 'remote با نام origin تعریف نشده است.' -Hint 'نمونه: git remote add origin <URL>'
    }

    $remoteUrl = ($remoteUrlLines | Select-Object -First 1).Trim()

    Write-StepBanner -Title 'مرحله ۱: همگام‌سازی گیت'

    & git fetch --prune
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 1 -Message 'git fetch با خطا متوقف شد.' -Hint 'به اتصال شبکه/دسترسی مخزن دقت کنید.'
    }

    & git pull --rebase --autostash
    $pullExit = $LASTEXITCODE
    if ($pullExit -ne 0) {
        $conflictOutput = & git ls-files -u
        if ($LASTEXITCODE -eq 0 -and $conflictOutput) {
            Exit-WithHint -Code 2 -Message 'تعارض در به‌روزرسانی گیت رخ داده است.' -Hint 'فایل‌های در تعارض را حل کرده و سپس git rebase --continue را اجرا کنید.'
        }

        Exit-WithHint -Code 1 -Message "git pull --rebase ناموفق بود (کد خروج $pullExit)." -Hint 'خروجی git pull را بررسی و مشکل همگام‌سازی را رفع کنید.'
    }

    Write-StepBanner -Title 'مرحله ۲: اجرای تست‌ها'

    $pythonCandidates = @(
        (Join-Path -Path $repoRoot -ChildPath '.venv/bin/python'),
        (Join-Path -Path $repoRoot -ChildPath '.venv/bin/python3'),
        (Join-Path -Path $repoRoot -ChildPath '.venv/Scripts/python.exe'),
        (Join-Path -Path $repoRoot -ChildPath '.venv/Scripts/python')
    )

    $pythonPath = $null
    foreach ($candidate in $pythonCandidates) {
        if (Test-Path -Path $candidate) {
            $pythonPath = (Resolve-Path -Path $candidate).Path
            break
        }
    }

    if (-not $pythonPath) {
        $pythonCmd = Get-Command -Name python -ErrorAction SilentlyContinue
        if ($null -eq $pythonCmd) {
            Exit-WithHint -Code 1 -Message 'مفسر Python پیدا نشد.' -Hint 'مطمئن شوید مجازی‌ساز یا Python سیستم در دسترس باشد.'
        }

        $pythonPath = $pythonCmd.Path
    }

    $workerArgs = @('-n', '1')
    $pytestArgs = @('--maxfail=1', '-q', '--override-ini', 'addopts=') + $workerArgs

    $testLines = @()
    & $pythonPath -m pytest @pytestArgs 2>&1 | Tee-Object -Variable testLines
    $testExit = $LASTEXITCODE

    if ($testExit -ne 0) {
        Exit-WithHint -Code 3 -Message 'اجرای pytest ناموفق بود.' -Hint 'خروجی pytest را بررسی و خطاهای تست را برطرف کنید.'
    }

    $passedMatch = $testLines | Select-String -Pattern '(\d+)\s+passed' | Select-Object -Last 1
    if ($passedMatch) {
        $testsCount = [int]$passedMatch.Matches[0].Groups[1].Value
    } else {
        $collectedMatch = $testLines | Select-String -Pattern 'collected\s+(\d+)' | Select-Object -Last 1
        if ($collectedMatch) {
            $testsCount = [int]$collectedMatch.Matches[0].Groups[1].Value
        } else {
            $testsCount = 0
        }
    }

    Write-StepBanner -Title 'مرحله ۳: اجرای دود'

    $smokeScript = Join-Path -Path $repoRoot -ChildPath 'scripts/smoke.ps1'
    if (Test-Path -Path $smokeScript) {
        & pwsh -NoLogo -NoProfile -File $smokeScript -TimeoutSec 12
        $smokeExit = $LASTEXITCODE
        if ($smokeExit -ne 0) {
            Exit-WithHint -Code 4 -Message 'اسکریپت دود (smoke) با خطا پایان یافت.' -Hint 'خروجی smoke.ps1 را بررسی و ایراد را برطرف کنید.'
        }
    } else {
        Write-Host 'اسکریپت دود یافت نشد؛ این مرحله عبور شد.' -ForegroundColor DarkGray
    }

    Write-StepBanner -Title 'مرحله ۴: جستجوی الگوهای اسرار'

    $diffOutput = & git diff HEAD --unified=0 --no-color 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joined = ($diffOutput -join [Environment]::NewLine)
        Exit-WithHint -Code 1 -Message "دریافت diff ناموفق بود: $joined" -Hint 'وضعیت مخزن را بررسی کنید.'
    }

    $secretPattern = [regex]'(?i)(PASSWORD|API_KEY|TOKEN|SECRET|PRIVATE_KEY)'
    $secretHits = New-Object System.Collections.Generic.List[psobject]
    [string]$activeFile = ''
    [int]$currentLine = 0

    foreach ($line in $diffOutput) {
        if ($line.StartsWith('diff ') -or $line.StartsWith('index ')) {
            continue
        }

        if ($line.StartsWith('+++')) {
            if ($line.Length -gt 6) {
                $activeFile = $line.Substring(6)
            } else {
                $activeFile = ''
            }

            continue
        }

        if ($line.StartsWith('@@')) {
            $match = [regex]::Match($line, '\+(\d+)(?:,(\d+))?')
            if ($match.Success) {
                $currentLine = [int]$match.Groups[1].Value
            } else {
                $currentLine = 0
            }

            continue
        }

        if ($line.StartsWith('+') -and -not $line.StartsWith('+++')) {
            $content = $line.Substring(1)
            if ($secretPattern.IsMatch($content)) {
                $snippet = $content.Trim()
                if ($snippet.Length -gt 160) {
                    $snippet = $snippet.Substring(0, 160)
                }

                $secretHits.Add([pscustomobject]@{
                        File    = $activeFile
                        Line    = $currentLine
                        Snippet = $snippet
                    })
            }

            $currentLine++
            continue
        }

        if ($line.StartsWith('-') -and -not $line.StartsWith('---')) {
            continue
        }
    }

    if ($secretHits.Count -gt 0) {
        Write-Error 'الگوی مشکوک به کلید/رمز پیدا شد.'
        foreach ($hit in $secretHits) {
            $filePath = if ([string]::IsNullOrWhiteSpace($hit.File)) { '<نامشخص>' } else { $hit.File }
            Write-Host ("{0}:{1} -> {2}" -f $filePath, $hit.Line, $hit.Snippet) -ForegroundColor Yellow
        }

        Write-Host 'موارد بالا را حذف یا رمزگذاری کنید و سپس دوباره تلاش کنید.' -ForegroundColor Yellow
        exit 5
    }

    $secretsCount = 0

    Write-StepBanner -Title 'مرحله ۵: بررسی کد و قالب'

    $lintTools = New-Object System.Collections.Generic.List[string]
    $preCommitCmd = Get-Command -Name pre-commit -ErrorAction SilentlyContinue
    if ($null -ne $preCommitCmd) {
        Write-Host 'اجرای pre-commit ...' -ForegroundColor DarkGray
        & pre-commit run -a
        $lintExit = $LASTEXITCODE
        if ($lintExit -ne 0) {
            Exit-WithHint -Code 6 -Message 'pre-commit با خطا متوقف شد.' -Hint 'گزارش pre-commit را مرور و اصلاحات لازم را اعمال کنید.'
        }

        $null = $lintTools.Add('pre-commit')
    } else {
        $fallbacks = @(
            @{ Name = 'ruff'; Args = @('check', '.') },
            @{ Name = 'black'; Args = @('--check', '.') },
            @{ Name = 'isort'; Args = @('--check-only', '.') }
        )

        foreach ($tool in $fallbacks) {
            $toolCmd = Get-Command -Name $tool.Name -ErrorAction SilentlyContinue
            if ($null -ne $toolCmd) {
                Write-Host ("اجرای {0} ..." -f $tool.Name) -ForegroundColor DarkGray
                & $tool.Name @($tool.Args)
                $lintExit = $LASTEXITCODE
                if ($lintExit -ne 0) {
                    Exit-WithHint -Code 6 -Message ("{0} با خطا پایان یافت." -f $tool.Name) -Hint ("خروجی {0} را بررسی کنید و سپس دوباره اسکریپت را اجرا نمایید." -f $tool.Name)
                }

                $null = $lintTools.Add($tool.Name)
            }
        }

        if ($lintTools.Count -eq 0) {
            Write-Host 'ابزار lint معتبری یافت نشد؛ این مرحله صرف‌نظر شد.' -ForegroundColor DarkGray
        }
    }

    $lintCount = $lintTools.Count

    Write-StepBanner -Title 'مرحله ۶: ثبت و ارسال تغییرات'

    & git add -A
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 1 -Message 'افزودن فایل‌ها به Staging ناموفق بود.' -Hint 'خروجی git add را بررسی و دوباره تلاش کنید.'
    }

    $statusLines = & git status --short
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 1 -Message 'دریافت وضعیت گیت موفق نبود.' -Hint 'git status را دستی اجرا و مشکل را رفع کنید.'
    }

    if (-not $statusLines) {
        Exit-WithHint -Code 1 -Message 'تغییری برای کامیت وجود ندارد.' -Hint 'پیش از اجرای اسکریپت تغییرات خود را اعمال کنید.'
    }

    Write-Host 'خلاصه وضعیت آمادهٔ کامیت:' -ForegroundColor DarkGray
    foreach ($line in $statusLines) {
        Write-Host $line
    }

    & git commit -m $trimmedMessage
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 1 -Message 'git commit شکست خورد.' -Hint 'بازبینی کنید که تغییرات آمادهٔ ثبت باشند.'
    }

    $commitShaLines = & git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) {
        Exit-WithHint -Code 1 -Message 'بازیابی SHA شکست خورد.' -Hint 'کامیت اخیر را دستی بررسی کنید.'
    }

    $commitSha = ($commitShaLines | Select-Object -First 1).Trim()

    if ($autoPushEnabled) {
        & git push -u origin $currentBranch
        $pushExit = $LASTEXITCODE
        if ($pushExit -ne 0) {
            Exit-WithHint -Code 7 -Message 'ارسال به origin ناموفق بود.' -Hint ("برای ارسال دستی: git push -u origin {0}" -f $currentBranch)
        }
    } else {
        Write-Host 'ارسال خودکار غیرفعال است؛ push انجام نشد.' -ForegroundColor DarkGray
    }

    Write-Host ''
    Write-Host '✅ همهٔ مراحل با موفقیت انجام شد.' -ForegroundColor Green
    Write-Host ("SHA: {0} | origin: {1} | تست‌ها={2} | لینت={3} | اسرار={4}" -f $commitSha, $remoteUrl, $testsCount, $lintCount, $secretsCount) -ForegroundColor Green
    exit 0
}
catch {
    $message = $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = $_ | Out-String
    }

    Exit-WithHint -Code 1 -Message ("خطای پیش‌بینی‌نشده: {0}" -f $message.Trim()) -Hint 'جزئیات خطا را بررسی و مجدداً تلاش کنید.'
}
