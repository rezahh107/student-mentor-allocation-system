Param([int]$Port=8001)

$ErrorActionPreference="Stop"

[Console]::OutputEncoding=[Text.Encoding]::UTF8; chcp 65001 | Out-Null



if (-not (Test-Path ".\.venv\Scripts\python.exe")) {

  py -3.11 -m venv .venv

}

.\.venv\Scripts\Activate.ps1



pip install -U pip | Out-Null

if (Test-Path ".\constraints-win.txt") {

  pip install -c constraints-win.txt -r requirements.txt

} else {

  pip install -r requirements.txt

}

pip check



$job = Start-Process -PassThru -FilePath python -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port $Port --workers 1"

Start-Sleep 3

try {

  Invoke-WebRequest "http://127.0.0.1:$Port/healthz" -UseBasicParsing | Out-Null

  Write-Host "✅ E2E startup OK on port $Port" -ForegroundColor Green

} finally {

  Stop-Process -Id $job.Id -Force

}

