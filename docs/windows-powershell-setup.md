# راهنمای راه‌اندازی Student Mentor Allocation روی Windows (PowerShell 7)

این نسخهٔ سخت‌شدهٔ راهنما یک مسیر سریع (TL;DR)، چک‌های پیش‌نیاز، اعتبارسنجی محیط، اجرای سرویس و اسموک‌تست‌های قابل اجرا با PowerShell 7+ را در اختیار شما قرار می‌دهد. تمامی پیام‌های خطا به‌صورت فارسی و قطعی طراحی شده‌اند تا با سیاست‌های مخزن سازگار بمانند.【F:Start-App.ps1†L1-L203】【F:win-dev-setup.ps1†L1-L327】

## TL;DR (یک‌باره)
```powershell
# PowerShell 7.4+ ، Python 3.11 x64 و Git باید نصب شده باشند
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .[dev]
```

## ۱. پیش‌نیازها و چک‌های فوری

برای اطمینان از آماده بودن سیستم، دستورات زیر را در PowerShell اجرا کنید؛ تمام آن‌ها فقط خواندنی هستند.

```powershell
# PowerShell 7.4+ و معماری ۶۴-بیتی
$PSVersionTable.PSVersion
[Environment]::Is64BitProcess

# Python 3.11 x64 و معماری
Get-Command py
py -3.11 -c "import platform, sys; print(platform.python_version()); print(platform.architecture()[0]); print(sys.maxsize > 2**32)"

# Git نصب شده است
Get-Command git

# فعال‌سازی تنظیمات CRLF و مسیرهای طولانی (برای این مخزن)
git config core.autocrlf true
git config core.longpaths true

# خروجی UTF-8 برای ورودی/خروجی متنی
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

> **یادآوری:** اسکریپت تشخیصی `tools/win/diagnose.ps1` همین چک‌ها را به‌صورت JSON ثبت می‌کند و هیچ تغییری در رجیستری یا تنظیمات سیستمی نمی‌دهد.【F:tools/win/diagnose.ps1†L1-L145】

## ۲. آماده‌سازی محیط مجازی و وابستگی‌ها

1. مخزن را کلون کرده و در PowerShell 7.4+ وارد پوشهٔ ریشه شوید.
2. محیط مجازی مخصوص Python 3.11 را فعال کرده و pip را به‌روزرسانی کنید:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -U pip setuptools wheel
   ```
3. نصب و به‌روزرسانی بسته‌ها را با پیکربندی توسعه انجام دهید:
   ```powershell
   pip install -e .[dev]
   ```
   در صورت بروز خطای وابستگی، اسکریپت `Start-App.ps1` به صورت خودکار تلاش می‌کند نصب editable را تکرار کند.【F:Start-App.ps1†L117-L139】

## ۳. پیکربندی متغیرهای محیطی و آماده‌سازی سرویس‌ها

1. قالب متغیرهای محیطی توسعه را کپی کنید:
   ```powershell
   Copy-Item .env.example .env.dev -Force:$false
   ```
2. در صورت نیاز، سرویس‌های وابسته (PostgreSQL/Redis) را با Docker Compose بالا بیاورید:
   ```powershell
   docker compose -f docker-compose.dev.yml up -d
   ```
3. اطمینان حاصل کنید متغیرهای `DATABASE_URL`، `REDIS_URL` و `METRICS_TOKEN` در `.env.dev` مقداردهی شده‌اند؛ در غیر این صورت `Start-App.ps1` خطای پیکربندی فارسی صادر می‌کند.【F:Start-App.ps1†L133-L139】

## ۴. اعتبارسنجی محیط

پس از فعال بودن محیط مجازی، فرمان‌های زیر را اجرا کنید. تمام خطاهای احتمالی با پیام قطعی فارسی نمایش داده می‌شوند.

```powershell
# بررسی وجود AGENTS.md (در صورت فقدان، خطا: «پروندهٔ AGENTS.md یافت نشد؛ لطفاً اضافه کنید.»)
python scripts/verify_agents.py

# اطمینان از جدید بودن ابزارهای ساخت
python -m pip install -U pip setuptools wheel

# نصب/تأیید وابستگی‌ها در حالت editable
pip install -e .[dev]

# نگهبان مسیر PYTHONPATH
python scripts/guard_pythonpath.py
```

## ۵. اجرا و مشاهدهٔ رفتار سرویس

### ۵.۱ اجرای هماهنگ‌شده

```powershell
pwsh -File .\Start-App.ps1
```

- اسکریپت فوق پیش از اجرای FastAPI در صورت نیاز نصب editable را تکرار می‌کند، فایل‌های `.env.dev` و `logs/` را بارگذاری/ایجاد کرده و خروجی استاندارد را به فرمت JSON (شامل `correlation-id`) هدایت می‌کند.【F:Start-App.ps1†L117-L188】
- در حالت شکست، پیام‌های فارسی و کد خروجی مشخص بازگردانده می‌شوند (کد ۲ برای وابستگی، کد ۱ برای سایر خطاها).【F:Start-App.ps1†L160-L203】

### ۵.۲ دسترسی به متریک‌ها و لاگ‌ها

- مسیر `/metrics` با توکن محافظت می‌شود؛ مقدار `METRICS_TOKEN` را در هدر `X-Metrics-Token` قرار دهید.【F:Start-App.ps1†L133-L139】
- برای مشاهدهٔ جریان لاگ‌ها از دستور زیر استفاده کنید:
  ```powershell
  Get-Content .\logs\app-stdout.log -Wait
  ```
- خطاهای ساختاری (JSON) در `logs/app-stderr.log` نیز با همان روش قابل مشاهده هستند.

## ۶. اسموک‌تست و ابزارهای تشخیصی

### ۶.۱ اجرای اسموک‌تست رسمی

```powershell
pwsh -File .\win-dev-setup.ps1 -Base 'http://127.0.0.1:25119'
```

این اسکریپت در صورت توقف سرویس، ابتدا `Start-App.ps1` را فراخوانی کرده و سپس آماده بودن مسیرهای `/readyz`، `/ui/health` و `/metrics` را با هدر مناسب بررسی می‌کند. تمام پیام‌ها به صورت فارسی و قطعی ثبت می‌شوند.【F:win-dev-setup.ps1†L5-L327】

### ۶.۲ اسموک‌تست‌های دستی با pytest

```powershell
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q `
  tests/scripts/test_pythonpath_guard.py `
  tests/windows_service/test_start_app_script.py
```

- در صورت نیاز به اجرای کامل تست‌ها، نصب افزونه‌های اضافی با همان فرمان `pip install -e .[dev]` کفایت می‌کند.

### ۶.۳ اسکریپت تشخیصی ویندوز

```powershell
pwsh -File .\tools\win\diagnose.ps1
```

- خروجی به‌صورت JSON و با فیلد `correlation_id` ثابت تولید می‌شود و شامل وضعیت نسخهٔ PowerShell، Python 3.11 x64، pip، Git، تنظیمات CRLF/longpaths و UTF-8 است. هیچ تغییری در سیستم اعمال نمی‌شود و پیام‌های عدم موفقیت به زبان فارسی ارائه می‌شوند.【F:tools/win/diagnose.ps1†L1-L145】

## ۷. ادامهٔ کار پس از آماده‌سازی

- از فرمان زیر برای جمع‌آوری وضعیت سرویس استفاده کنید:
  ```powershell
  Get-Content .\logs\app-stdout.log -Wait
  ```
- برای توقف سرویس از `Stop-App.ps1` یا `Ctrl+C` در جلسهٔ اجرا شده استفاده کنید (در صورت وجود).
- برای مشاهدهٔ متریک‌ها از مرورگر یا ابزار خط فرمان با هدر مناسب استفاده نمایید.

---

گواهی: AGENTS.md::8 Testing & CI Gates
