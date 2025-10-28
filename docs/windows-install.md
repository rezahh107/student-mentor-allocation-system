# Windows installation guide

این راهنمای گام‌به‌گام کاربران Windows 10/11 را از نصب پیش‌نیازها تا اجرای کامل سامانه **ImportToSabt** هدایت می‌کند. سناریوهای سه‌گانه (محیط بومی، WSL2 و Docker Desktop) پوشش داده شده‌اند و در پایان یک مسیر پیشنهادی همراه با ۱۰ فرمان پشت‌سرهم ارائه می‌شود.

> **پروفایل سامانه**
>
> * **ASGI entrypoint:** `main:app` (ساخته‌شده از `sma.phase6_import_to_sabt.app.app_factory.create_application`).
> * **تنظیمات محیطی:** کلاس `AppConfig` در `sma/phase6_import_to_sabt/app/config.py` با پیشوند `IMPORT_TO_SABT_` و فیلدهای تو در تو (`__`).
> * **سرویس‌های اجباری:** PostgreSQL 16 (درگاه پیش‌فرض `5432`) و Redis 7 (درگاه پیش‌فرض `6379`).
> * **دروازه‌های امنیتی:** گارد توکن `/metrics`، RBAC با نقش‌های `ADMIN` و `MANAGER`، جریان‌های امضا برای دانلودها، و آرشیو/ممیزی فعال.

## Prerequisites

همه فرمان‌ها را در PowerShell 7+ با **UTF-8** اجرا کنید:

```powershell
$PSStyle.OutputRendering = 'ANSI'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null
```

۱. **بسته‌ها (با winget):**

```powershell
winget install --id Python.Python.3.11 --exact --source winget
winget install --id Git.Git --source winget
winget install --id Microsoft.VisualStudio.2022.BuildTools --source winget --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools"
winget install --id OpenSSL.Light --source winget
```

۲. **گزینه‌های جایگزین:** اگر از Chocolatey استفاده می‌کنید:

```powershell
choco install python --version=3.11.9
choco install git
choco install visualstudio2022buildtools --package-parameters "--add Microsoft.VisualStudio.Workload.VCTools"
choco install openssl.light
```

۳. **ابزارهای اختیاری:**

* [Docker Desktop](https://www.docker.com/products/docker-desktop/) (برای بخش‌های Docker/WSL2).
* [WSL2 + Ubuntu 22.04](https://learn.microsoft.com/windows/wsl/install) برای اجرای لینوکسی.

> **نکتهٔ دایرکتوری** — پیشنهاد می‌شود ریپو را در مسیری مانند `E:\StudentMentor` کلون کنید تا با طول مسیرهای کوتاه و بدون فاصله کار کنید.

## Environment configuration

کلاس `AppConfig` مقادیر زیر را می‌پذیرد؛ کلیدها با ساختار `IMPORT_TO_SABT_<FIELD>` و برای فیلدهای تو در تو از `__` استفاده می‌کند. اسکریپت `scripts/win/20-create-env.ps1` تمام این مقادیر را با خواندن مدل Pydantic تولید می‌کند و فایل‌های `.env.example.win` و (در صورت فعال‌سازی سوییچ `-WriteEnv`) فایل `.env` را به صورت اتمیک می‌سازد.

نمونهٔ محتوای `.env.example.win` (خروجی پیش‌فرض اسکریپت):

```dotenv
# توکن‌های مراقبت (RBAC و متریک)
METRICS_TOKEN=dev-metrics-ro
IMPORT_TO_SABT_AUTH__SERVICE_TOKEN=dev-service-token
IMPORT_TO_SABT_AUTH__METRICS_TOKEN=dev-metrics-ro
IMPORT_TO_SABT_AUTH__TOKENS_ENV_VAR=TOKENS
IMPORT_TO_SABT_AUTH__DOWNLOAD_SIGNING_KEYS_ENV_VAR=DOWNLOAD_SIGNING_KEYS
IMPORT_TO_SABT_AUTH__DOWNLOAD_URL_TTL_SECONDS=900
IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true
TOKENS=[{"value":"dev-service-token","role":"ADMIN"}]
DOWNLOAD_SIGNING_KEYS=[{"kid":"legacy","secret":"dev-download-secret","state":"active"}]

# اتصال به Redis و PostgreSQL
IMPORT_TO_SABT_REDIS__DSN=redis://localhost:6379/0
IMPORT_TO_SABT_REDIS__NAMESPACE=import_to_sabt
IMPORT_TO_SABT_REDIS__OPERATION_TIMEOUT=0.2
IMPORT_TO_SABT_DATABASE__DSN=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
IMPORT_TO_SABT_DATABASE__STATEMENT_TIMEOUT_MS=500

# پیکربندی گیت وی
IMPORT_TO_SABT_RATELIMIT__NAMESPACE=imports
IMPORT_TO_SABT_RATELIMIT__REQUESTS=30
IMPORT_TO_SABT_RATELIMIT__WINDOW_SECONDS=60
IMPORT_TO_SABT_RATELIMIT__PENALTY_SECONDS=120
IMPORT_TO_SABT_OBSERVABILITY__SERVICE_NAME=import-to-sabt
IMPORT_TO_SABT_OBSERVABILITY__METRICS_NAMESPACE=import_to_sabt
IMPORT_TO_SABT_TIMEZONE=Asia/Tehran
IMPORT_TO_SABT_READINESS_TIMEOUT_SECONDS=0.5
IMPORT_TO_SABT_HEALTH_TIMEOUT_SECONDS=0.2
IMPORT_TO_SABT_ENABLE_DEBUG_LOGS=false
IMPORT_TO_SABT_ENABLE_DIAGNOSTICS=false
EXPORT_STORAGE_DIR=storage\\exports
```

> **چرا METRICS_TOKEN؟** مسیر `/metrics` تنها با توکن فقط‌خواندنی پاسخ‌گو است. اگر `METRICS_TOKEN` یا `IMPORT_TO_SABT_AUTH__METRICS_TOKEN` مقداردهی نشود پیام «توکن متریک تنظیم نشده است.» باز می‌گردد.

## Native virtual environment (Recommended)

۱. **تشخیص سیستم:**

```powershell
pwsh -NoLogo -File scripts/win/00-diagnose.ps1
```

۲. **ساخت و فعال‌سازی ویرچوال‌اِن‌وایرونمنت:**

```powershell
pwsh -NoLogo -File scripts/win/10-venv-install.ps1 -ConstraintsPath constraints-win.txt
.\.venv\Scripts\Activate.ps1
```

اسکریپت `10-venv-install.ps1` موارد زیر را تضمین می‌کند:

* استفاده از `py -3.11` یا `python` سازگار؛ نسخه‌های دیگر رد می‌شوند.
* ارتقای `pip`, `setuptools`, `wheel` و نصب بسته‌ها با احترام به `constraints-win.txt`.
* اجتناب قطعی از نصب `uvloop` در Windows (در صورت نصب، حذف می‌شود) و نصب `tzdata==2025.2`.
* اجرای `pip check` بدون هشدار.

۳. **تولید فایل‌های محیطی:**

```powershell
pwsh -NoLogo -File scripts/win/20-create-env.ps1 -WriteEnv
```

این اسکریپت تمام کلیدها را مستقیماً از `AppConfig` استخراج می‌کند، مقدارهای پیش‌فرض (از جمله JSONهای `TOKENS` و `DOWNLOAD_SIGNING_KEYS`) را درج می‌کند، فایل را به‌صورت اتمیک (`.part` → `rename`) می‌نویسد و در پایان خلاصه‌ای فارسی از تعداد کلیدهای الزامی/اختیاری چاپ می‌کند.

۴. **راه‌اندازی سرویس‌های پشتیبان:**

```powershell
pwsh -NoLogo -File scripts/win/30-services.ps1 -Mode Docker -ComposeFile docker-compose.dev.yml
```

ویژگی‌های کلیدی:

* backoff نمایی به‌همراه jitter تعیین‌گر برای آماده‌سازی سرویس‌ها
* ثبت لاگ JSON با `Correlation-ID` در `reports/win-smoke/services-log.jsonl`
* شمارندهٔ Prometheus-friendly در `reports/win-smoke/services-metrics.prom`
* حالت `-Action Cleanup` برای `docker compose down -v --remove-orphans` یا پاک‌سازی سرویس‌های محلی با `redis-cli`/`psql`

۵. **اجرای برنامه:**

```powershell
pwsh -NoLogo -File scripts/win/40-run.ps1 -Host 0.0.0.0 -Port 8000 -Background -StateDir tmp\win-app
```

این اسکریپت فایل‌های `.env` را بارگذاری می‌کند، وجود `METRICS_TOKEN` را الزامی می‌کند و سپس `python -m uvicorn main:app` را با پروسهٔ جداگانه اجرا می‌کند. شناسهٔ فرایند و نشانی endpoint در `tmp\win-app\state.json` ذخیره می‌شود.

۶. **تست دود (Smoke):**

```powershell
pwsh -NoLogo -File scripts/win/50-smoke.ps1 -BaseUrl http://127.0.0.1:8000 -StateDir tmp\win-app
```

این تست‌ها موارد زیر را پوشش می‌دهند:

* `/healthz` و `/readyz` → پاسخ موفق با زمان‌سنجی ثبت‌شده.
* `/docs` → فقط در صورت فعال بودن `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS` (در نمونه فعال است).
* `/metrics` بدون هدر → کد 403 با پیام فارسی «دسترسی به /metrics نیازمند توکن فقط‌خواندنی است.»
* `/metrics` با هدر `Authorization: Bearer dev-metrics-ro` → کد 200 و متریک‌های Prometheus.
* فراخوانی RBAC: `POST /api/jobs` با توکن سرویسی → زنجیرهٔ middleware به ترتیب `RateLimit → Idempotency → Auth` و نقش `ADMIN` در پاسخ.
* برگهٔ دانلود/خروجی آزمایشی (`GET /api/exports/csv`) → پاسخ JSON با نقش کاربر.

نتایج کامل در `reports/win-smoke/` ذخیره می‌شود (`smoke-log.jsonl`, `smoke-summary.json`, `http-responses.json`). اسکریپت قبل و بعد از اجرای درخواست‌ها به‌ترتیب `Start-Services` و `Cleanup-State`/`Stop-Services` را فرامی‌خواند تا Redis/PostgreSQL بدون حالت باقی بمانند.

> **بودجهٔ کارایی:** برای حفظ توافق با [AGENTS.md](../AGENTS.md) باید `p95 ≤ 200ms` (همراه با backoff) و مصرف حافظهٔ `≤ 300MB` در محیط‌های تستی رعایت شود. متریک‌های `services-metrics.prom` و خروجی `/metrics` این اعداد را پایش می‌کنند.

## WSL2 path

۱. در Windows ویژگی‌های WSL و ماشین مجازی را فعال کنید و Ubuntu 22.04 را نصب نمایید.
۲. در ترمینال Ubuntu:

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip git redis-server postgresql
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install -e . -c constraints.txt
pip check
```

۳. PostgreSQL/Redis را در WSL راه‌اندازی کنید (systemd یا `service redis-server start`، `service postgresql start`).
۴. فایل `.env` را با `python -m scripts.win.env_exporter` (یا اجرای `20-create-env.ps1` از Windows و کپی به WSL) بسازید.
۵. اجرای برنامه:

```bash
METRICS_TOKEN=dev-metrics-ro uvicorn main:app --host 0.0.0.0 --port 8000
```

۶. دستورات smoke مانند PowerShell ولی با `curl`:

```bash
curl -sS http://127.0.0.1:8000/healthz | jq
curl -sS -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/metrics
curl -sS -H "Authorization: Bearer dev-metrics-ro" http://127.0.0.1:8000/metrics | head
```

## Docker Desktop path

اگر ترجیح می‌دهید همه چیز در کانتینر باشد:

۱. Docker Desktop را فعال کنید (Linux containers).
۲. فایل‌های `.env` را با `20-create-env.ps1` تولید کنید.
۳. یک تصویر سبک بسازید (Dockerfile نمونه):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt constraints-win.txt ./
RUN pip install --upgrade pip wheel setuptools \
    && pip install --no-cache-dir -r requirements.txt \
       --constraint constraints.txt \
    && pip uninstall -y uvloop || true
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python","-m","uvicorn","main:app","--host","0.0.0.0","--port","8000"]
```

۴. Compose فایل ساده (از سرویس‌های آمادهٔ ریپو استفاده می‌کند):

```yaml
services:
  app:
    build: .
    env_file:
      - .env
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - postgres
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    ports: ["5432:5432"]
```

۵. اجرای compose:

```powershell
docker compose up --build
```

۶. smoke test را از Windows یا داخل کانتینر اجرا کنید (`pwsh -File scripts/win/50-smoke.ps1 -BaseUrl http://127.0.0.1:8000`).

## Troubleshooting

| پیام | علت | راه‌حل |
|------|------|--------|
| «uvloop does not support Windows» | تلاش برای نصب uvloop | اسکریپت `10-venv-install.ps1` آن را حذف می‌کند؛ در صورت مشاهده `pip uninstall uvloop` اجرا و دوباره نصب را با `-SkipUvloopGuard:$false` انجام دهید. |
| «منطقهٔ زمانی در دسترس نیست؛ بستهٔ tzdata…» | نصب `tzdata` انجام نشده | `pip install tzdata==2025.2 --constraint constraints-win.txt` را اجرا و `pip check` را تکرار کنید. |
| نویز پلاگین pytest | Pytest در Windows پلاگین‌های سراسری را لود می‌کند | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q` یا از `sitecustomize.py` ریپو استفاده کنید. |
| `No module named main` یا ورودی نادرست | اجرای uvicorn با ماژول اشتباه | `main:app` تنها نقطهٔ ورود پشتیبانی‌شده است (به `main.py` مراجعه کنید). |
| درگاه مشغول (مثلاً 8000) | سرویس دیگر در حال استفاده از پورت است | `Get-NetTCPConnection -LocalPort 8000 | Format-Table -AutoSize` سپس `Stop-Process -Id <PID>` یا پورت دیگری به `40-run.ps1` بدهید. |
| کلیدهای تو در تو در `.env` ناقص است | ویرایش دستی کلیدها | همیشه از `20-create-env.ps1` استفاده کنید؛ کلیدها باید مانند `IMPORT_TO_SABT_REDIS__DSN` باشند. |
| مشکل در کدپیج یا حروف فارسی | PowerShell در UTF-8 نیست | `chcp 65001` و تنظیم `OutputEncoding` طبق بخش مقدمات. |

## TL;DR (Recommended path)

۱۰ فرمان پشت‌سرهم برای یک راه‌اندازی بومی استاندارد:

```powershell
cd E:\
git clone https://github.com/OWNER/student-mentor-allocation-system.git
cd student-mentor-allocation-system
pwsh -NoLogo -File scripts/win/00-diagnose.ps1
pwsh -NoLogo -File scripts/win/10-venv-install.ps1 -ConstraintsPath constraints-win.txt
pwsh -NoLogo -File scripts/win/20-create-env.ps1 -WriteEnv
pwsh -NoLogo -File scripts/win/30-services.ps1 -Mode Docker -ComposeFile docker-compose.dev.yml
pwsh -NoLogo -File scripts/win/40-run.ps1 -Background -StateDir tmp\win-app
pwsh -NoLogo -File scripts/win/50-smoke.ps1 -StateDir tmp\win-app
pwsh -NoLogo -File scripts/win/30-services.ps1 -Action Cleanup -Mode Docker -ComposeFile docker-compose.dev.yml
```

> **نتیجهٔ پیشنهادی:** محیط بومی (venv) سریع‌ترین مسیر است؛ فقط در صورت نیاز به ابزارهای خاص لینوکسی/کانتینری به سراغ WSL2 یا Docker بروید.

گزارش اجرای اسکریپت‌های دود به‌صورت خودکار در مسیر `reports/win-smoke/` ذخیره می‌شود:

- `smoke-log.jsonl` و `smoke-summary.json` شامل لاگ JSON با `Correlation-ID` (بدون افشای توکن‌ها)
- `http-responses.json` برای تشخیص سریع وضعیت درخواست‌ها
- فایل‌های متریک سرویس‌ها `services-metrics.prom` با شمارش Retry (Prometheus-ready)

## Evidence

- Evidence: AGENTS.md::6 Atomic I/O — اسکریپت‌های `20-create-env.ps1` و `50-smoke.ps1` نوشتن فایل‌ها را با `.part` و `rename` انجام می‌دهند.
- Evidence: AGENTS.md::8 Testing & CI Gates — سرویس‌ها و دود تست‌ها گزارش Prometheus و آرشیو `reports/win-smoke/` تولید می‌کنند و در CI (`windows-smoke.yml`) اجرا می‌شوند.
- Evidence: AGENTS.md::10 User-Visible Errors — پیام‌های `/metrics` و خطاهای اسکریپت‌ها به‌صورت فارسی و تعیین‌گر مستندسازی شده‌اند.

