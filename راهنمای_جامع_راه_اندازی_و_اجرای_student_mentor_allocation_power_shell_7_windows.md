## 🚀 راهنمای اجرای Windows برای FastAPI (پروژه Import-to-Sabt)

> هدف: راه‌اندازی سریع، پایدار و قابل‌تکرار روی Windows 10/11 با venv. (WSL/Docker: در پایان اشاره کوتاه شده)

------

### 1️⃣ پیش‌نیازها (Windows Native) — ~150 کلمه

- Python 3.11+، Git، PostgreSQL، Redis.
- اطمینان از PATH صحیح و UTF-8.
- سرویس‌های PostgreSQL/Redis را لوکال اجرا کنید.

```powershell
# نصب پایه‌ها (در صورت نیاز با ادمین)
winget install -e --id Python.Python.3.11
winget install -e --id Git.Git
winget install -e --id PostgreSQL.PostgreSQL
winget install -e --id Redis.Redis

# بررسی نسخه‌ها
python --version
git --version

# نکته‌ها:
# 1) اگر PostgreSQL/Redis قبلاً نصب شده‌اند، از همین‌ها استفاده کنید.
# 2) PowerShell را UTF-8 کنید تا لاگ‌ها و .env درست خوانده شود:
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

------

### 2️⃣ راه‌اندازی سریع — گام‌به‌گام (Windows venv)

- متادیتا: **factory** وجود دارد → ماژول اجرا:
   `sma.phase6_import_to_sabt.app.app_factory:create_application`
- فایل‌های وابستگی: `requirements*.txt` + `constraints-win.txt`
- پکیج ناسازگار با Windows: `uvloop`

```powershell
# 1) کلون و ورود
git clone <REPO_URL>
cd <PROJECT_FOLDER>

# 2) ساخت venv و فعال‌سازی
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -U pip setuptools wheel

# 3) نصب وابستگی‌ها (استفاده از constraints ویندوز)
# اگر constraints-win.txt موجود است (وجود دارد طبق متادیتا):
pip install -r requirements.txt -c constraints-win.txt
# (در صورت نیاز dev/test را بعداً نصب کنید)

# 4) حذف پکیج ناسازگار ویندوز
pip uninstall -y uvloop

# 5) نصب/هم‌نسخه‌سازی پکیج‌های کلیدی (طبق پین‌های متادیتا)
pip install "fastapi==0.110.3" "uvicorn==0.37.0" "pydantic==2.7.4" "tzdata==2025.2"

# 6) صحت نصب
pip check
python -c "import fastapi,uvicorn; print('Deps OK')"
```

**نکته‌های حیاتی**

- اگر ارور حل‌نشدنی دیدید، یک‌بار `pip install -r requirements.txt -c constraints-win.txt --force-reinstall` امتحان کنید.
- روی Windows با `--workers 1` اجرا کنید (محدودیت multiprocessing).

------

### 3️⃣ فایل `.env` — نمونه واقعی بر پایه متادیتا (Prefix و Delimiter)

- `env_prefix`: `IMPORT_TO_SABT_`
- `env_nested_delimiter`: `__`
- **ضروری‌ها**:
  - `IMPORT_TO_SABT_DATABASE__DSN` (PostgreSQL)
  - `IMPORT_TO_SABT_REDIS__DSN` (Redis)
- **پیش‌فرض‌ها** (در صورت عدم تنظیم):
  - `IMPORT_TO_SABT_TIMEZONE=Asia/Tehran`
  - `IMPORT_TO_SABT_RATE_LIMIT__REQUESTS=30`
  - `IMPORT_TO_SABT_RATE_LIMIT__WINDOW_SECONDS=60`
  - `IMPORT_TO_SABT_OBSERVABILITY__METRICS_NAMESPACE=import_to_sabt`

```powershell
# ایجاد .env (نمونه)
@'
# === Database (Required)
IMPORT_TO_SABT_DATABASE__DSN=postgresql+asyncpg://user:pass@localhost:5432/import_to_sabt

# === Redis (Required)
IMPORT_TO_SABT_REDIS__DSN=redis://localhost:6379/0
IMPORT_TO_SABT_REDIS__NAMESPACE=sma-import

# === Auth / Metrics
# اگر /metrics محافظت‌شده است، توکن را اینجا بگذارید:
IMPORT_TO_SABT_AUTH__METRICS_TOKEN=<put-a-strong-token-here>
# در صورت نیاز به خواندن توکن‌ها از یک متغیر دیگر:
IMPORT_TO_SABT_AUTH__TOKENS_ENV_VAR=IMPORT_TO_SABT_AUTH__METRICS_TOKEN

# === Rate Limit (اختیاری - پیش‌فرض‌ها برقرارند)
IMPORT_TO_SABT_RATE_LIMIT__REQUESTS=30
IMPORT_TO_SABT_RATE_LIMIT__WINDOW_SECONDS=60

# === Observability (اختیاری)
IMPORT_TO_SABT_OBSERVABILITY__METRICS_NAMESPACE=import_to_sabt

# === Timezone (اختیاری)
IMPORT_TO_SABT_TIMEZONE=Asia/Tehran
'@ | Out-File -FilePath .env -Encoding utf8
```

**تولید توکن امن در Windows**

```powershell
python - <<'PY'
import secrets; print(secrets.token_hex(32))
PY
```

------

### 4️⃣ اجرای سرور (factory) — پایدار و قابل‌توسعه

- **Factory موجود است** → از فلگ `--factory` استفاده کنید.
- برای توسعه: `--reload`، برای Windows: `--workers 1`.

```powershell
# اجرای توسعه
uvicorn sma.phase6_import_to_sabt.app.app_factory:create_application `
  --factory --host 127.0.0.1 --port 8000 --reload --workers 1

# اجرای ساده بدون reload (پیشنهادی برای smoke)
# uvicorn sma.phase6_import_to_sabt.app.app_factory:create_application --factory --host 0.0.0.0 --port 8000 --workers 1
```

**اگر پروژه اسکریپت ویندوز داشت (مثل Start-App.ps1)، ترجیح با uvicorn مستقیم است تا عیوب محیطی سریع شناسایی شود.**

------

### 5️⃣ تست سریع — Health و Metrics

```powershell
# Health (رایج: /health یا /healthz)
try { (Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing).StatusCode } catch { $_.Exception.Message }

# OpenAPI Docs
start http://127.0.0.1:8000/docs

# Metrics (در صورت محافظت، با Bearer توکن)
$headers = @{ Authorization = "Bearer $env:IMPORT_TO_SABT_AUTH__METRICS_TOKEN" }
try { (Invoke-WebRequest http://127.0.0.1:8000/metrics -Headers $headers -UseBasicParsing).StatusCode } catch { $_.Exception.Message }
```

------

### 6️⃣ عیب‌یابی TOP-5 — خطایابی سریع

| خطا                                        | علت محتمل                              | راه‌حل فوری                                                   |
| ------------------------------------------ | -------------------------------------- | ------------------------------------------------------------ |
| `ModuleNotFoundError: uvloop`              | uvloop ناسازگار با Windows             | `pip uninstall -y uvloop`                                    |
| `ImportError: cannot import app`           | اجرای اشتباه entrypoint                | از factory درست اجرا کنید: `uvicorn sma.phase6_import_to_sabt.app.app_factory:create_application --factory` |
| `ValueError: Invalid config / Missing var` | `.env` ناقص؛ متغیرهای Required ست نشده | `IMPORT_TO_SABT_DATABASE__DSN` و `IMPORT_TO_SABT_REDIS__DSN` را اضافه کنید؛ سپس ری‌استارت |
| `Connection refused (Postgres/Redis)`      | سرویس‌ها بالا نیستند یا DSN غلط         | سرویس‌ها را Start کنید، پورت/پسورد را بررسی کنید، DSN را اصلاح کنید |
| `tzdata error / timezone`                  | نسخه ناسازگار یا نبود tzdata           | `pip install tzdata==2025.2`                                 |

**ابزارهای کمکی**

```powershell
# پورت در اشغال:
netstat -ano | findstr :8000
# پایان‌دادن به پردازش:
taskkill /PID <PID> /F

# بررسی Encoding برای جلوگیری از UnicodeDecodeError
chcp 65001
```

------

### 7️⃣ TL;DR — ده فرمان تا اجرا (Copy-Paste)

```powershell
git clone <REPO_URL>
cd <PROJECT_FOLDER>

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -U pip setuptools wheel

pip install -r requirements.txt -c constraints-win.txt
pip uninstall -y uvloop
pip install "fastapi==0.110.3" "uvicorn==0.37.0" "pydantic==2.7.4" "tzdata==2025.2"

@'
IMPORT_TO_SABT_DATABASE__DSN=postgresql+asyncpg://user:pass@localhost:5432/import_to_sabt
IMPORT_TO_SABT_REDIS__DSN=redis://localhost:6379/0
IMPORT_TO_SABT_AUTH__METRICS_TOKEN=REPLACE_ME
'@ | Out-File -FilePath .env -Encoding utf8

uvicorn sma.phase6_import_to_sabt.app.app_factory:create_application --factory --host 127.0.0.1 --port 8000 --reload --workers 1
start http://127.0.0.1:8000/docs
```

------

### ℹ️ نکات پایانی

- **WSL/Docker (اختیاری):** اگر به uvloop یا workers بیشتر نیاز دارید، اجرای همان دستور uvicorn در WSL Ubuntu یا یک کانتینر Docker پیشنهاد می‌شود.
- **Production روی Windows:** `--workers 1`، لاگ‌برداری ساختاریافته، و سرویس‌دهی پشت IIS/Nginx/Reverse Proxy را در نظر بگیرید.
- **پایداری:** هر بار قبل از اجرا `pip check` و صحت `.env` را بررسی کنید.







------

# 📘 راهنمای جامع اجرای پروژه Python روی Windows (Student Mentor Allocation System)

> **پروفایل پروژه (از ZIP):**
>
> - **نوع:** وب‌سرویس **FastAPI** (ASGI) + ابزار CLI (Typer)
> - **EntryPoint:** ماژول `main:app` (فایل **`main.py`** در ریشه ریپو)
> - **Python:** **3.11.x** (طبق `pyproject.toml`: `>=3.11,<3.12`)
> - **وابستگی‌های سیستمی:** **PostgreSQL 16** (پورت 5432)، **Redis 7** (پورت 6379)
> - **اجرای ویندوز:** اسکریپت‌های **`Start-App.ps1`** و سرویس WinSW آماده است
> - **ENV مینیمال برای سرویس ویندوز:** `DATABASE_URL`, `REDIS_URL`, `METRICS_TOKEN`
> - **ENV کامل برای FastAPI:** کلیدهای با پیشوند `IMPORT_TO_SABT_*` (نمونه آماده در **`.env.example`**)
> - **مستندات داخلی پروژه برای ویندوز:** `docs/windows-install.md` (همسو با این راهنما)

------

## 0) 📑 فهرست کامل راهنما + ⚡️ Quick Start

### 📑 فهرست

- [1) مقدمه](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-1-مقدمه-و-آشنایی)
- [2) پیش‌نیازها (ویندوز)](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-2-آمادهسازی-سیستم-pre-requisites)
- [3) دریافت و آماده‌سازی پروژه](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-3-دریافت-و-آمادهسازی-پروژه)
- [4) ساخت و فعال‌سازی venv](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-4-ایجاد-محیط-مجازی-virtual-environment)
- [5) نصب پکیج‌ها](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-5-نصب-وابستگیها-dependencies)
- [6) پیکربندی ENV](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-6-پیکربندی-configuration)
- [7) اجرای برنامه](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-7-اجرای-برنامه)
- [8) تست و اعتبارسنجی](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-8-تست-و-اعتبارسنجی)
- [9) رفع خطاهای رایج](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-9-عیب‌یابی-جامع-troubleshooting)
- [10) نکات Production](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-10-بهینهسازی-و-production)
- [11) اسکریپت‌های کمکی](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-11-اسکریپتهای-کمکی)
- [12) مرجع سریع دستورات](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-12-مرجع-سریع)
- [13) پیوست‌ها و کمک](https://chatgpt.com/g/g-p-68d0308e4e208191bc7a5ce5370b43ed/c/6900a3a8-d7b0-8328-b889-9318ac8cffdb#-13-پیوستها)

### ⚡️ راه‌اندازی سریع (۱۰ فرمان پشت‌سرهم)

```powershell
# 1) مسیر پروژه
cd C:\Projects
# 2) پوشه بساز و ZIP را اینجا Extract کن
mkdir student-mentor && cd student-mentor
# 3) ساخت venv
py -3.11 -m venv .venv
# 4) فعال‌سازی venv
.\.venv\Scripts\Activate.ps1
# 5) ارتقای ابزار نصب
python -m pip install --upgrade pip setuptools wheel
# 6) نصب پروژه (حالت توسعه)
pip install -e ".[dev]"
# 7) کپی ENV نمونه
copy .env.example .env
# 8) ویرایش .env (DB/Redis/METRICS را تنظیم کن)
notepad .env
# 9) اجرای Uvicorn (ASGI)
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
# 10) باز کردن مرورگر
start http://127.0.0.1:8000/docs
```

------

## 1) 🎯 مقدمه و آشنایی

**این برنامه چیست؟** یک وب‌سرویس FastAPI برای **تخصیص خودکار دانش‌آموزان به پشتیبانان** با قوانین مشخص (اعتبارسنجی، تولید شمارنده، تخصیص بهینه، گزارش‌گیری).

**پیش‌نمایش خروجی:** پس از اجرا، در **`/docs`** مستند Swagger را می‌بینید؛ **`/metrics`** با توکن، متریک‌های Prometheus را می‌دهد؛ و APIهای تخصیص/گزارش فعال‌اند.

**زمان تقریبی اجرا:**

- 🟢 مبتدی: 30–45 دقیقه
- 🟡 متوسط: 15–20 دقیقه
- 🔴 حرفه‌ای: 5–10 دقیقه

------

## 2) 🖥️ آماده‌سازی سیستم (Pre-requisites)

### چک‌لیست

- □ Windows 10 (1903+) یا Windows 11
- □ **Python 3.11.x**
- □ Git (آخرین نسخه)
- □ Visual C++ Build Tools (برای برخی چرخ‌ها/اکستنشن‌ها)
- □ **PostgreSQL 16** در 5432
- □ **Redis 7** در 6379
- □ دسترسی Administrator برای نصب‌ها

### بررسی نسخه ویندوز

1. Win + R → `winver` → Enter
2. نسخه/بیلد را یادداشت کنید.

### نصب خودکار (پیشنهادی—قابل کپی در PowerShell Admin)

> اگر winget ندارید، روش دستی را انجام دهید.

```powershell
# PowerShell را با Run as Administrator باز کنید
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force

# Python 3.11 و Git
winget install -e --id Python.Python.3.11
winget install -e --id Git.Git

# Visual C++ Build Tools
winget install -e --id Microsoft.VisualStudio.2022.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --quiet --wait --norestart"

# PostgreSQL 16 (اگر در winget موجود)
winget install -e --id PostgreSQL.PostgreSQL
```

### نکته درباره Redis روی ویندوز

Redis باینری رسمی ویندوز ندارد. دو مسیر امن دارید:

- **مسیر A (نیّت این راهنما: بومی):** نصب Redis بومی (مثل Memurai Community) و اجرای سرویس روی 6379.
- **مسیر B (اشاره یک‌خطی مجاز):** اگر Docker دارید: یک کانتینر Redis سریعاً بالا بیاورید. *(اختیاری)*

> این راهنما ادامه را برای هر دو حالت پوشش می‌دهد. اگر Redis/PG را بومی نصب کردید، عالی. اگر Docker در دسترس دارید، اسکریپت آماده پروژه هم کانتینرها را بالا می‌آورد.

------

## 3) 📦 دریافت و آماده‌سازی پروژه

### از فایل ZIP

1. فایل ZIP را به مسیر پیشنهادی کپی کنید: `C:\Projects\student-mentor\`
2. راست‌کلیک → **Extract All…** → داخل همان مسیر.

### ساختار مهم پروژه

```
project-root/
├─ main.py                 ← ASGI entrypoint  →  main:app
├─ Start-App.ps1           ← راه‌انداز ویندوز + readiness
├─ Start_App.bat           ← لانچر Batch برای PowerShell
├─ .env.example            ← نمونه ENV
├─ pyproject.toml          ← پیکربندی پروژه (Python ≥3.11,<3.12)
├─ requirements*.txt       ← لیست پکیج‌ها/قیود (اختیاری)
├─ docker-compose.dev.yml  ← سرویس‌های Redis/Postgres (اختیاری)
└─ src/sma/...             ← کدهای FastAPI، امنیت، متریک، ...
```

------

## 4) 🔒 ایجاد محیط مجازی (Virtual Environment)

```powershell
# از ریشه پروژه
py -3.11 -m venv .venv

# فعال‌سازی در PowerShell
.\.venv\Scripts\Activate.ps1

# علامت موفقیت: ابتدای خط باید (venv) ببینید
```

> اگر ExecutionPolicy خطا داد:
>  `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force`

------

## 5) 📦 نصب وابستگی‌ها (Dependencies)

### مسیر پیشنهادی (همسو با pyproject)

```powershell
python -m pip install --upgrade pip setuptools wheel
# نصب حالت توسعه با ابزار تست/کیفیت
pip install -e ".[dev]"
```

### مسیر جایگزین (فایل‌های pinned)

```powershell
# در صورت نیاز به قیود ثابت
pip install -c constraints.txt -r requirements.txt
```

> روی ویندوز، پکیج‌های ناسازگار مانند `uvloop` **خودکار نصب نمی‌شوند** (دارند شرط `platform_system != "Windows"`). نیازی به تغییر دستی نیست.

------

## 6) ⚙️ پیکربندی (Configuration)

### گزینه ۱ — ساده‌ترین: از نمونه

```powershell
copy .env.example .env
notepad .env
```

**مقادیر حداقل برای اجرای FastAPI (طبق `.env.example`):**

```env
ENVIRONMENT=development

# Redis (JSON config)
IMPORT_TO_SABT_REDIS={"dsn":"redis://127.0.0.1:6379/0"}

# Postgres (psycopg v3 DSN)
IMPORT_TO_SABT_DATABASE={"dsn":"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres","statement_timeout_ms":5000}

# Auth & Metrics
IMPORT_TO_SABT_AUTH={"service_token":"dev-admin","metrics_token":"dev-metrics"}
METRICS_TOKEN=dev-metrics

# برای نمایش /docs در محیط توسعه:
IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true
```

> **نکته:** اگر از **سرویس ویندوز** (WinSW + `windows_service/controller.py`) استفاده می‌کنید، حداقل متغیرهای **`DATABASE_URL`**, **`REDIS_URL`**, **`METRICS_TOKEN`** نیز پشتیبانی می‌شوند:

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres
REDIS_URL=redis://127.0.0.1:6379/0
METRICS_TOKEN=dev-metrics
```

> **ساخت کلید امن (اختیاری):**

```powershell
python - <<'PY'
import secrets; print(secrets.token_hex(32))
PY
```

سپس مقدار را برای فیلدهای امنیتی (مثل `SIGNING_KEY_HEX`) در `.env` قرار دهید.

------

## 7) 🚀 اجرای برنامه

### روش A — مستقیم با Uvicorn (ساده و شفاف)

```powershell
# venv باید فعال باشد
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

- API: `http://127.0.0.1:8000/`

- مستندات: `http://127.0.0.1:8000/docs` *(در صورت `PUBLIC_DOCS=true`)*

- متریک‌ها (با توکن):

  ```powershell
  $h=@{"Authorization"="Bearer dev-metrics"}
  Invoke-WebRequest http://127.0.0.1:8000/metrics -Headers $h
  ```

### روش B — اسکریپت ویندوز آماده (Readiness + راه‌انداز)

```powershell
# اجرای لانچر پروژه (پورت پیش‌فرض این مسیر معمولا 25119)
pwsh -ExecutionPolicy Bypass -File .\Start-App.ps1
```

- این اسکریپت اول **وابستگی‌ها را Probe** می‌کند و با خطای فارسیِ قابل‌درک متوقف می‌شود اگر Redis/PG در دسترس نباشند.

### (اختیاری) روشن‌کردن سرویس‌ها با Docker

> اشاره یک‌خطیِ مجاز:

```powershell
# اگر Docker Desktop دارید:
pwsh .\scripts\win\30-services.ps1 -Action Start -Mode Docker
```

> اگر بومی نصب کرده‌اید، صرفاً سلامت پورت‌ها را می‌سنجید:

```powershell
pwsh .\scripts\win\30-services.ps1 -Action Start -Mode ValidateLocal
```

------

## 8) ✅ تست و اعتبارسنجی

### Health و متریک

```powershell
# Health (مثلاً /docs /openapi.json /metrics)
pwsh .\run_server_check.ps1 -BaseUrl http://127.0.0.1:8000 -OutputJsonPath server_check.json -OutputLogPath server_check.log
```

### اجرای تست‌ها

```powershell
# تست‌های سریع و سازگار با CI
pytest -q
# یا از CLI خود پروژه (Typer):
smasm test
```

------

## 9) 🔧 عیب‌یابی جامع (Troubleshooting)

**۱) `python` یا `pip` شناخته نمی‌شود**

- راه‌حل: پنجره جدید PowerShell باز کنید؛ یا از `py -3.11` استفاده کنید. مطمئن شوید Python از Microsoft Store/winget نصب شده و PATH به‌روز است.

**۲) خطای ExecutionPolicy در فعال‌سازی venv**

- راه‌حل:

  ```powershell
  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
  ```

**۳) خطای اتصال به دیتابیس (`could not connect to server`)**

- PostgreSQL روشن نیست یا پورت 5432 اشغال است. سرویس را Start کنید، یا پورت را در `.env` اصلاح کنید.

**۴) Redis در ویندوز**

- اگر بومی نصب نیست، سریع‌ترین راه (اختیاری) با Docker: بالا.

**۵) `CONFIG_MISSING: «پیکربندی ناقص…»` از `Start-App.ps1`**

- مقدار ENV را در `.env` تکمیل/تصحیح کنید (حداقل `DATABASE_URL`, `REDIS_URL`, `METRICS_TOKEN`).

**۶) `/docs` باز نمی‌شود**

- `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` را در `.env` بگذارید و سرویس را ری‌استارت کنید.

**۷) `/metrics` خطای 403 می‌دهد**

- هدر توکن لازم است: `Authorization: Bearer <METRICS_TOKEN>`.

**۸) Port در حال استفاده است**

```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**۹) خطاهای ساخت چرخ‌ها/اکستنشن‌ها**

- Visual C++ Build Tools نصب و ریبوت شود. سپس `pip install -e ".[dev]"` را تکرار کنید.

**۱۰) Encoding/Unicode در ترمینال**

```powershell
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

------

## 10) ⚡ بهترین شیوه‌ها برای Production

- **SECURITY:** `PUBLIC_DOCS=false`، توکن‌ها را امن نگه دارید، `/metrics` را پشت فایروال/ServiceToken بگذارید.
- **PERF:** روی ویندوز Uvicorn با چند Worker محدود (CPU هسته‌ها)؛ پروفایل مصرف RAM/CPU.
- **OBSERVABILITY:** Prometheus scrape از `/metrics` با هدر؛ JSON-Logs ساختاریافته فعال.
- **DB/Cache:** Connection pooling برای Postgres؛ Redis با Persistence مناسب.
- **BACKUPS & DR:** پشتیبان‌گیری از Postgres؛ مانیتورینگ خطا و هشدار ظرفیت Mentorها.

------

## 11) 🎯 اسکریپت‌های کمکی

### `install_all.bat`

```bat
@echo off
setlocal
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
 "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force; ^
  if (-Not (Get-Command py -ErrorAction SilentlyContinue)) { Write-Host 'Install Python 3.11 first.'; exit 1 }; ^
  py -3.11 -m venv .venv; ^
  .\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel; ^
  .\.venv\Scripts\python.exe -m pip install -e .[dev]; ^
  if (-Not (Test-Path .env)) { Copy-Item .env.example .env }"
endlocal
```

### `run_dev.bat`

```bat
@echo off
setlocal
call .\.venv\Scripts\activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
endlocal
```

### `update.bat`

```bat
@echo off
setlocal
call .\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .[dev]
endlocal
```

### `create_shortcuts.ps1`

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')

$lnk = $WshShell.CreateShortcut((Join-Path $Desktop 'Run StudentMentor.lnk'))
$lnk.TargetPath = (Resolve-Path '.\.venv\Scripts\python.exe')
$lnk.Arguments  = '-m uvicorn main:app --host 127.0.0.1 --port 8000 --reload'
$lnk.WorkingDirectory = (Get-Location).Path
$lnk.Save()
```

------

## 12) 📋 مرجع سریع

| عملیات             | دستور                                                |
| ------------------ | ---------------------------------------------------- |
| ساخت venv          | `py -3.11 -m venv .venv`                             |
| فعال‌سازی venv      | `.\.venv\Scripts\Activate.ps1`                       |
| نصب پروژه (dev)    | `pip install -e ".[dev]"`                            |
| اجرای سرویس        | `python -m uvicorn main:app --reload`                |
| لانچر آماده ویندوز | `pwsh -ExecutionPolicy Bypass -File .\Start-App.ps1` |
| سلامت سرویس        | `pwsh .\run_server_check.ps1`                        |
| تست‌ها              | `pytest -q` یا `smasm test`                          |
| توقف اجرا          | `Ctrl + C`                                           |
| غیرفعال‌سازی venv   | `deactivate`                                         |

------

## 13) 📚 پیوست‌ها

- فایل‌های کلیدی:
  - **`main.py`** (ورود FastAPI به‌صورت `app = create_application()`)
  - **`.env.example`** (نمونه تنظیمات کامل با پیشوند `IMPORT_TO_SABT_`)
  - **`Start-App.ps1`** (راه‌انداز ویندوز + readiness probe)
  - **`docker-compose.dev.yml`** (اختیاری برای Redis/Postgres)
  - **`scripts/win/\*.ps1`** (نصب venv، ساخت ENV، مدیریت سرویس‌ها، اسموک)
- گرفتن کمک: Issue در ریپو، یا لاگ‌های `server_check.log` و خروجی‌های اسکریپت‌ها.

------

# 🧾 Quick Reference Card (A4)

**هدف:** اجرای محلی Student Mentor Allocation System روی Windows

1. Python 3.11، Git، VC++ Build Tools نصب
2. Postgres (5432) و Redis (6379) آماده
3. `py -3.11 -m venv .venv` → فعال‌سازی
4. `pip install -e ".[dev]"`
5. `copy .env.example .env` → ویرایش اتصال‌ها
6. `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`
7. بازکردن `http://127.0.0.1:8000/docs`
8. متریک‌ها با هدر `Authorization: Bearer dev-metrics`
9. تست‌ها: `pytest -q`
10. عیب‌یابی: `run_server_check.ps1`

------

# ⚡ 10-Command Quick Start (برای کاربران باتجربه)

```powershell
cd C:\Projects
mkdir student-mentor && cd student-mentor
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
copy .env.example .env
notepad .env
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
start http://127.0.0.1:8000/docs
```

------

# 🌳 Decision Tree (اگر مشکل دارم، کجا بروم؟)

- **سرویس بالا نمی‌آید؟**
   ↳ `Start-App.ps1` را اجرا کن → پیام فارسی خطا را بخوان → ENV ناقص؟ پورت بسته؟ Redis/PG در دسترس هستند؟
- **/docs باز نمی‌شود؟**
   ↳ `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` در `.env` هست؟ ری‌استارت کن.
- **/metrics خطای 403؟**
   ↳ هدر `Authorization: Bearer <METRICS_TOKEN>` اضافه کن.
- **DB/Redis وصل نمی‌شود؟**
   ↳ سرویس‌ها روشن؟ پورت‌ها 5432/6379 بازند؟ DSN در `.env` درست است؟
- **Package نصب نمی‌شود؟**
   ↳ VC++ Build Tools نصب است؟ `pip install -e ".[dev]"` را تکرار کن.

------

# ✅ Success Checklist

-  Python 3.11 و venv فعال
-  پکیج‌ها بدون خطا نصب شدند
-  `.env` با مقادیر درست (DB/Redis/Metrics)
-  `uvicorn main:app` بالا و `http://127.0.0.1:8000/docs` قابل مشاهده
-  `/metrics` با هدر توکن قابل دسترس
-  تست سریع پروژه (`pytest -q`) پاس شد

------

خیلی هم عالی — چون Docker Desktop داری، بخش‌های مخصوص Docker رو هم اضافه کردم و کل پکیج ابزارهای جانبی رو هم آماده کردم (نصاب یک‌کلیکی، ویزارد تعاملی، هِلث‌چک/داشبورد، تمپلیت PDF و…).

## 📦 فایل‌های آمادهٔ استفاده (دانلود مستقیم)

- **One-Click Installer (Batch):** [install_everything.bat](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/install_everything.bat)
- **Health Check Script (PowerShell):** [health_check.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/health_check.ps1)
- **Interactive Setup Wizard (PowerShell):** [setup_wizard.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/setup_wizard.ps1)
- **Real-time Health Dashboard (PowerShell):** [health_dashboard.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/health_dashboard.ps1)
- **PDF Template (Markdown + CSS):** [guide_template.md](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/guide_template.md) · [guide.css](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/guide.css)

> همهٔ اسکریپت‌ها UTF-8 و برای ویندوز آماده‌اند (CRLF). اگر ExecutionPolicy خطا داد:
>  `PowerShell (Admin)` → `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

------

# ♻️ افزوده‌های ویژهٔ Docker Desktop (Windows)

### پیش‌نیازها

- Windows 10 1903+ یا Windows 11
- **Docker Desktop** (WSL2 backend فعال)، Settings → General: ☑ Use the WSL 2 based engine
- Resources (پیشنهادی): 4 CPU · 4–6GB RAM · 2GB Swap

### بالا آوردن سرویس‌ها (Redis/Postgres) با Compose موجود پروژه

```powershell
# از ریشه‌ی پروژه
docker compose -f docker-compose.dev.yml up -d

# بررسی سلامت
docker ps
docker compose ls
docker logs <container_name> --tail=100

# توقف/پاکسازی (اختیاری)
docker compose -f docker-compose.dev.yml down
# دیتای Postgres در Volume نگه داشته می‌شود؛ برای پاکسازی کامل:
# docker volume rm student-mentor-allocation-system-main_pgdata
```

**اتصال در .env:**

- `redis://127.0.0.1:6379/0`
- `postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres`

> اگر Docker Desktop در دسترس نبود، روی ویندوز می‌توان Redis محلی (مثل Memurai Community) و PostgreSQL ویندوز نصب کرد؛ راهنمای قبلی این حالت را هم پوشش داده است.

------

# 🧭 آنچه اضافه شد (طبق درخواست تو)

## 1) 🖼️ Diagrams (Mermaid + توضیح)

### A) معماری سیستم

```mermaid
flowchart LR
  subgraph Client
    BROWSER[Browser / HTTP Client]
  end

  subgraph App[FastAPI Application Layer]
    API[ASGI: main:app (Uvicorn)]
    AUTH[Auth Middleware (Service Token)]
    LOGIC[Business Logic (Allocation)]
    METRICS["/metrics (Prometheus)"]
  end

  subgraph Data[Data Stores]
    PG[(PostgreSQL :5432)]
    RD[(Redis :6379)]
  end

  BROWSER -->|HTTPS/HTTP| API
  API --> AUTH --> LOGIC
  LOGIC -->|Read/Write| PG
  LOGIC -->|Cache| RD
  API <-->|/docs /openapi.json| BROWSER
  METRICS -->|scrape| BROWSER
```

**توضیح:** درخواست کاربر به ASGI (Uvicorn) می‌رسد، میدلور احراز هویت (توکن سرویس) اعمال می‌شود، منطق تخصیص با Postgres و Redis کار می‌کند، و `/metrics` داده‌های Prometheus را می‌دهد.

### B) Data Flow Diagram

```mermaid
sequenceDiagram
  participant C as Client
  participant A as FastAPI
  participant AU as Auth
  participant BL as Business Logic
  participant DB as PostgreSQL
  participant R as Redis

  C->>A: HTTP Request (JSON)
  A->>AU: Validate Token
  AU-->>A: OK / 401
  A->>BL: Call Use-Case
  BL->>R: Cache Lookup (optional)
  alt cache miss
    BL->>DB: Query/Tx
    DB-->>BL: Rows
    BL->>R: Cache Set (optional)
  end
  BL-->>A: Result
  A-->>C: HTTP Response (JSON)
```

### C) Installation Flow

```mermaid
flowchart TD
  A[Check Prerequisites] --> B[Install Python 3.11]
  B --> C[Setup venv]
  C --> D[pip install -e .[dev]]
  D --> E[Configure .env]
  E --> F[Start Redis/Postgres (Docker)]
  F --> G[Run App (Uvicorn)]
  G --> H[Validate: /health /docs /metrics]
```

### D) Screenshot Mocks (چه نمایش بدهیم)

1. **Swagger UI (/docs):** لیست endpoints، دکمه Try it out، یک نمونه پاسخ 200.
2. **/metrics:** چند تا متریک Prometheus (مثلاً `process_cpu_seconds_total`)، هدر Authorization=Bearer.
3. **CMD با venv:** `(venv)` در ابتدای خط، اجرای `uvicorn`.
4. **.env در Notepad++:** بخش‌های `IMPORT_TO_SABT_DATABASE/REDIS/AUTH`.
5. **خروجی `pytest -q`:** `= N passed, 0 failed =`.
6. **PowerShell Start-App.ps1:** خطوط readiness / پیام‌های فارسی.

------

## 2) 🎬 اسکریپت ویدیو 5–7 دقیقه‌ای (فارسی)

**[00:00–00:45] مقدمه**
 متن: «سلام! توی این ویدیو Student Mentor Allocation System رو روی Windows نصب و اجرا می‌کنیم…»
 نمایش: لوگو/عنوان، سوییچ به `/docs`.

**[00:45–02:00] پیش‌نیازها**
 Scene‌ها:

- Microsoft Store → Python 3.11 (15s)
- `py -3.11 --version` (10s)
- Docker Desktop + `docker compose version` (10s)
- `netstat :5432 / :6379` برای چک پورت‌ها (20s)
   نریشن: چرا Postgres/Redis.

**[02:00–04:00] Quick Start**
 نمایش 10 فرمان تیترشده (کپی‌پیست). اجرای مرحله‌به‌مرحله؛ هایلایت `(venv)` و `pip install -e ".[dev]"`. باز کردن `.env` و تنظیم DSNها.

**[04:00–05:30] تست**
 بازکردن `/docs`، اجرای `/health`، تست `/metrics` با هدر.

**[05:30–06:30] رفع ExecutionPolicy**
 نمایش خطا + `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

**[06:30–07:00] جمع‌بندی**
 اسلاید منابع: راهنمای کامل، GitHub Issues، Quick Reference Card.

------

## 3) 🤖 Setup Wizard (PowerShell)

**کد کامل:** [setup_wizard.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/setup_wizard.ps1)
 امکانات: منو تعاملی، بررسی پیش‌نیاز، ساخت venv و نصب deps، پیکربندی `.env`، بالا آوردن Compose، اجرای health check، اجرای اپ.

- رنگ‌ها: `Write-Host -ForegroundColor`
- Progress: `Write-Progress`
- لاگ: `setup_wizard.log`
- حالت سایلنت: `.\setup_wizard.ps1 -Silent`
- فایل پیکربندی: `-ConfigFile` (قابل گسترش)

------

## 4) 🔧 Health Check Dashboard

- **Health Check تک‌مرحله‌ای:** [health_check.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/health_check.ps1)
- **داشبورد زندهٔ ساده:** [health_dashboard.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/health_dashboard.ps1)
   نمایش CPU/RAM، وضعیت `/health` و `/metrics`، رفرش خودکار هر ۵ ثانیه، کلیدهای `R` و `Q`.

------

## 5) 📄 Template PDF (Pandoc/wkhtmltopdf)

- Markdown: [guide_template.md](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/guide_template.md)
- CSS: [guide.css](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/guide.css)

**دستورات تبدیل (نمونه):**

```bash
# Pandoc + xelatex
pandoc guide_template.md -o guide.pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=1in \
  -V fontsize=11pt \
  --toc --toc-depth=3 \
  --highlight-style=tango

# یا با wkhtmltopdf (اگر HTML می‌سازی)
wkhtmltopdf --enable-local-file-access guide.html guide.pdf
```

فونت‌های فارسی پیشنهادی: Vazirmatn / Sahel.

------

## 6) 🧰 One-Click Installer (Batch)

**کد کامل:** [install_everything.bat](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/install_everything.bat)
 کارها: چک Python 3.11، چک پورت‌های PG/Redis، ساخت venv، نصب `.[dev]`، ساخت/بازکردن `.env`، اعتبارسنجی سادهٔ ENV، اجرای `pytest -q` (اختیاری)، استارت Uvicorn و باز کردن `/docs`، لاگ کامل در `installation.log`.

------

## 7) 📊 جداول مقایسه‌ای (خلاصهٔ تصمیم)

### اجرای سرویس‌ها

| ویژگی        | Direct Uvicorn | Start-App.ps1 | WinSW Service  | Docker Compose |
| ------------ | -------------- | ------------- | -------------- | -------------- |
| سادگی        | ⭐⭐⭐⭐⭐          | ⭐⭐⭐⭐          | ⭐⭐⭐            | ⭐⭐             |
| پایداری      | ⭐⭐             | ⭐⭐⭐           | ⭐⭐⭐⭐           | ⭐⭐⭐⭐           |
| Hot Reload   | ✅              | ✅             | ❌              | ⚠️ (Bind Mount) |
| Auto-restart | ❌              | ⚠️             | ✅              | ✅              |
| لاگ/متریک    | پایه           | خوب           | عالی           | عالی           |
| مناسب        | Dev            | Dev/Staging   | Prod (Windows) | DevOps/Cloud   |

### Redis روی ویندوز

| روش               | Performance | راه‌اندازی | Production | هزینه  | توصیه       |
| ----------------- | ----------- | --------- | ---------- | ------ | ----------- |
| Memurai Community | ⚡⚡⚡⚡        | ⭐⭐⭐⭐      | ⭐⭐⭐        | رایگان | ویندوز بومی |
| Docker Redis      | ⚡⚡⚡         | ⭐⭐⭐⭐⭐     | ⭐⭐⭐⭐       | رایگان | همه‌جا       |
| WSL2 Redis        | ⚡⚡⚡⚡        | ⭐⭐⭐       | ⭐⭐⭐⭐       | رایگان | توسعه       |

------

## 8) ❓ FAQ (۲۰ سؤالِ پرکاربرد)

### A) عمومی

1. **برای چه کسانی مناسب است؟**
    کسانی که می‌خواهند یک سرویس FastAPI با Postgres/Redis را سریع روی ویندوز اجرا کنند.
2. **رایگان است؟** بله، کد پروژه و دستورالعمل‌ها رایگان‌اند.
3. **نیاز به دانش برنامه‌نویسی دارم؟** نه؛ این راهنما مبتدی‌پسند است.
4. **روی Mac/Linux هم می‌شود؟** بله؛ با اصلاح دستورات شِل.
5. **زمان راه‌اندازی؟** مبتدی ~۳۰–۴۵ دقیقه، حرفه‌ای ~۵–۱۰ دقیقه.

### B) نصب

1. **Python 3.12؟** خیر، پروژه روی `>=3.11,<3.12` پین شده است.
2. **pip خطای C++ می‌دهد؟** Build Tools 2022 را نصب کنید.
3. **Redis روی ویندوز؟** بهترین مسیر توسعه: Docker یا Memurai.
4. **PostgreSQL نصب نیست؟** با Docker Compose بالا بیاورید.
5. **venv فعال نمی‌شود؟** ExecutionPolicy را RemoteSigned کنید.

### C) پیکربندی

1. **.env را از کجا شروع کنم؟** از `.env.example` کپی بگیرید و DSNها را تنظیم کنید.
2. **پورت را تغییر بدهم؟** پرامتر `--port` در Uvicorn یا ENV اختصاصی.
3. **/docs باز نمی‌شود؟** `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` بگذارید (فقط Dev).
4. **METRICS_TOKEN چیست؟** توکن Bearer برای `/metrics`.

### D) اجرا

1. **پورت 8000 اشغال است؟** `netstat -ano | findstr :8000` + `taskkill /PID <PID> /F`.
2. **به‌عنوان سرویس ویندوز؟** با WinSW و `windows_service/controller.py`.
3. **لاگ‌ها کجا؟** خروجی ترمینال یا اسکریپت‌های نصب/داشبورد (logs/*.log).
4. **Docker کند است؟** منابع Docker Desktop را در Settings → Resources افزایش دهید.

### E) Performance/Monitoring

1. **چند worker؟** Dev: 1 با `--reload`؛ Prod: بر اساس هسته‌ها.
2. **مانیتورینگ؟** `/metrics` را با هدر Bearer به Prometheus وصل کنید؛ Grafana برای داشبورد.

*(در صورت نیاز، ۳۰+ سؤال هم می‌نویسم—گفتی فقط بگو تا کاملش کنم.)*

------

# 🧩 فرمت خروجی نهایی (مطابق خواستهٔ انتهایی تو)

## بخش 1: One-Click Installer

کد کامل در فایل: **[install_everything.bat](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/install_everything.bat)**

## بخش 2: Health Check Script

کد کامل در فایل: **[health_check.ps1](sandbox:/mnt/data/sma_windows_bundle_20251028_113224/health_check.ps1)**

## بخش 3: FAQ جامع

بخش **FAQ (۲۰ سؤال)** بالا را اضافه کردم؛ اگر بخواهی تا ۳۰+ سؤال گسترش می‌دهم.

------

## ✨ قدم بعدی پیشنهادی

- اگر می‌خواهی **فقط با Docker** همه‌چیز (App+DB+Redis) بالا بیاید، برایت یک `Dockerfile.app` و یک `docker-compose.app.yml` هم تولید می‌کنم تا با یک فرمان `docker compose up -d` کل استک اجرا شود. فقط بگو ترجیح می‌دهی پیکربندی ENV را چگونه به کانتینر بدهیم (bind-mount `.env` یا `env_file`).