# SmartAllocPY Environment Guide


## Quick Start

### TL;DR
- `./quick_start.bat` یا `pwsh -ExecutionPolicy Bypass -File ./Start-App.ps1`
- `python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Set `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` and `METRICS_TOKEN=<token>` in dev/CI before running server checks; docs stay locked otherwise and `/metrics` always requires `Authorization: Bearer <token>`.
- Run `python setup.py` to install dependencies, set `PYTHONPATH`, configure VS Code, and generate `activate` scripts.
- Use `activate.bat` (Windows) or `source ./activate.sh` (macOS/Linux) before working in a new shell.
- Launch diagnostics with `python scripts/environment_doctor.py` to validate the environment and apply optional fixes.

> 📘 **جدید برای Windows**: راهنمای کامل نصب و اجرای بومی/WSL2/Docker در [docs/windows-install.md](docs/windows-install.md) موجود است.

#### Windows quickstart (10 فرمان)

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

> نتیجه: اجرای کامل ImportToSabt با RBAC، گارد متریک، اسموک‌تست و پاک‌سازی سرویس‌ها؛ گزارش‌ها در `reports/win-smoke/` ذخیره می‌شوند (`smoke-log.jsonl`, `smoke-summary.json`, `http-responses.json`).

<!--dev-quick-start:start-->

## Quick Start (Dev)

### پیش‌نیازها
- Python 3.11
- PostgreSQL (پورت 5432) و Redis (پورت 6379) روی سیستم محلی یا از طریق Docker Compose

### نصب

#### Windows (PowerShell 7)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
Copy-Item -Path .env.example -Destination .env -Force
```

#### Linux/macOS/WSL
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
cp .env.example .env
```

> ℹ️ اسکریپت `devserver.py` فایل `.env` موجود در ریشهٔ مخزن را به صورت خودکار بارگذاری می‌کند؛ نیازی به تنظیم دستی `PYTHONPATH` یا اشارهٔ صریح به فایل نیست.

#### نمونه تنظیمات محیطی (Nested ENV)
```env
IMPORT_TO_SABT_DATABASE__DSN=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/student_mentor
IMPORT_TO_SABT_DATABASE__STATEMENT_TIMEOUT_MS=500
IMPORT_TO_SABT_REDIS__DSN=redis://127.0.0.1:6379/0
IMPORT_TO_SABT_REDIS__NAMESPACE=import_to_sabt_local
IMPORT_TO_SABT_AUTH__SERVICE_TOKEN=dev-service-token
IMPORT_TO_SABT_AUTH__METRICS_TOKEN=dev-metrics-token
IMPORT_TO_SABT_TIMEZONE=Asia/Tehran
```

> 💡 برای نگاشت ساختار‌های تودرتو از الگوی `SECTION__FIELD` (دو زیرخط متوالی) استفاده کنید؛ مثال: `IMPORT_TO_SABT_REDIS__DSN`. این الگو با تنظیم جدید `env_nested_delimiter="__"` پشتیبانی می‌شود و با نمونهٔ `.env.example` همسو است.

### دیتابیس‌ها (اختیاری)
```bash
docker compose -f docker-compose.dev.yml up -d
```

فایل `docker-compose.dev.yml` یک نمونهٔ Redis و PostgreSQL تمیز برای توسعهٔ محلی راه‌اندازی می‌کند و می‌توان پس از اتمام کار با `docker compose -f docker-compose.dev.yml down` آن را جمع‌آوری کرد.

### اجرا

دو مسیر رسمی اجرا پشتیبانی می‌شود:

```bash
python devserver.py
```

```bash
uvicorn devserver:app --reload --host 0.0.0.0 --port 8000
```

> 🪟 برای اجرای یک‌مرحله‌ای در ویندوز می‌توانید از `scripts/dev.ps1` استفاده کنید؛ اسکریپت پس از فعال‌سازی ویرچوال‌انvironment، وجود `.env` را بررسی کرده و سپس سرور توسعه را با `devserver.py` اجرا می‌کند.

### اسموک‌تست
```bash
METRICS_TOKEN=dev-metrics scripts/smoke.sh
```

### تست‌ها و معیارهای پذیرش
- همیشه قبل از اجرای تست‌ها `pip check` را اجرا کنید تا ناسازگاری وابستگی‌ها گزارش شود.
- تست‌های واحد/ریگرشن به صورت پیش‌فرض بدون پلاگین اجرا می‌شوند (بارگذاری دستی `pytest-asyncio` در `pytest.min.ini` تضمین شده است):
  ```bash
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -c pytest.min.ini -m "not integration"
  ```
- برای اجرای تست‌های یکپارچه و پوشش سناریوهای حساس (ترتیب میان‌افزار، نرخ محدودسازی و پاک‌سازی Redis) متغیر `RUN_INTEGRATION=1` را مقداردهی کنید:
  ```bash
  RUN_INTEGRATION=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=0 pytest -q -c pytest.min.ini -m "integration"
  ```
  این پرچم همان متغیر محیطی است که در CI جهت فعال‌سازی شغل اختیاری استفاده می‌شود (`Settings → Variables → RUN_INTEGRATION`).
- وابستگی `pytest-asyncio>=0.23` در بخش dev نصب می‌شود و به کمک `pytest.min.ini` و `tests/conftest.py` حتی با غیرفعال بودن autoload به صورت صریح لود می‌گردد؛ در صورت نبود پلاگین، پیغام skip مشخصی مشاهده خواهید کرد.
- تست `tests/integration/test_middleware_order.py` تضمین می‌کند ترتیب میان‌افزارها همواره «RateLimit → Idempotency → Auth» باقی بماند.
- تست‌های `tests/integration/test_redis_dirty_state.py` و `tests/integration/test_rate_limit_smoke.py` بدون نیاز به سرویس خارجی، رفتار پاک‌سازی Redis و کنترل نرخ را شبیه‌سازی می‌کنند.

<!--dev-quick-start:end-->

### Windows (PowerShell 7)

راهنمای رسمی نصب ویندوز در فایل «[docs/windows-install.md](docs/windows-install.md)» شامل مسیر پیشنهادی بومی، گزینهٔ WSL2 و Docker، اسکریپت‌های `scripts/win/*.ps1` و اسموک‌تست‌های کامل است.

### 🧪 Windows Acceptance Checks

1. نصب Python 3.11 (مثال: `winget install Python.Python.3.11`).
2. در PowerShell (ریشهٔ ریپو) اجرا کنید:
   ```powershell
   Set-Location <repo>
   $env:IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS = "true"
   $env:METRICS_TOKEN = "dev-metrics"
   ```
3. با همان شل `.\run_application.bat` را اجرا کنید و Uvicorn را فعال نگه دارید.
4. در شل دوم دستور زیر را اجرا کنید تا خروجی JSON/LOG ذخیره شود:
   ```powershell
   pwsh -NoLogo -File .\run_server_check.ps1 -OutputJsonPath windows_check.json -OutputLogPath windows_check.log
   ```
5. خروجی انتظار می‌رود:
   - `/openapi.json`, `/docs`, `/redoc` → وضعیت 200 زمانی که `PUBLIC_DOCS=1`.
   - `/metrics` بدون هدر → وضعیت 403.
   - `/metrics` با `Authorization: Bearer dev-metrics` → وضعیت 200 و نتایج در فایل‌های JSON/LOG ثبت می‌شود.

### 🔁 CI Integration (Windows Smoke)

[![Windows Smoke](https://github.com/OWNER/student-mentor-allocation-system/actions/workflows/windows-smoke.yml/badge.svg)](https://github.com/OWNER/student-mentor-allocation-system/actions/workflows/windows-smoke.yml)

- Workflow `.github/workflows/windows-smoke.yml` enforces UTF-8 PowerShell, launches `tools/ci/win_smoke.ps1`, then runs `pytest` with warnings-as-errors.
- Strict Scoring v2 parser (`tools/ci/parse_pytest_summary.py`) must report **TOTAL 100/100**; CI fails otherwise.
- Determinism: parser/tests avoid wall-clock sources; timings rely on monotonic perf counters strictly for diagnostics.

## Import Refactor (src-layout fixer)
برای هماهنگی خودکار ایمپورت‌های مطلق با ساختار `src/` می‌توانید ابزار `tools/refactor_imports.py` را اجرا کنید. ابزار به صورت پیش‌فرض Dry-Run است و گزارش CSV/JSON تولید می‌کند.

**PowerShell 7 (Windows 11):**

```powershell
$env:PYTHONPATH="$PWD;$PWD\src"
\.\.venv\Scripts\python.exe tools\refactor_imports.py scan --report-csv out\refactor.csv --report-json out\refactor.json
\.\.venv\Scripts\python.exe tools\refactor_imports.py apply --fix-entrypoint main:app
\.\.venv\Scripts\python.exe tools\refactor_imports.py scan --serve-metrics --metrics-token token --metrics-port 9130
```

**Bash (Linux/macOS/WSL):**

```bash
export PYTHONPATH="$PWD:$PWD/src"
.venv/bin/python tools/refactor_imports.py scan --report-csv out/refactor.csv --report-json out/refactor.json
.venv/bin/python tools/refactor_imports.py apply --fix-entrypoint main:app
.venv/bin/python tools/refactor_imports.py scan --serve-metrics --metrics-token token --metrics-port 9130
```

برای اجرای تست‌های ابزار:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -c pytest.min.ini tests/refactor -q
```

برای بررسی بودجهٔ کارایی و گزارش ۵ بعدی:

```bash
.venv/bin/python strict_report.py --summary reports/pytest-summary.txt --json reports/pytest.json
```

برای جلوگیری از ورود ایمپورت‌های خام جدید، می‌توانید در فایل `.pre-commit-config.yaml` بخش زیر را اضافه کنید:

```yaml
- repo: local
  hooks:
    - id: forbid-bare-src-imports
      name: forbid bare src imports
      entry: python tools/refactor_imports.py scan
      language: system
      pass_filenames: false
```

## FastAPI Hardened Service Configuration
- `REDIS_NAMESPACE` و `REDIS_URL` برای تفکیک فضای کلید و اتصال به Redis استفاده می‌شوند؛ در CI مقدار `REDIS_URL` از سرویس `redis:7` تزریق می‌گردد.
- سیاست Retry Redis از طریق متغیرهای `REDIS_MAX_RETRIES` (پیش‌فرض ۳)، `REDIS_BASE_DELAY_MS`، `REDIS_MAX_DELAY_MS` و `REDIS_JITTER_MS` قابل تنظیم است.
- برای فعال‌سازی Fail-Open عمومی می‌توانید `RATE_LIMIT_FAIL_OPEN=1` را تنظیم کنید؛ GET ها در صورت خطا همیشه Fail-Open می‌شوند و `POST /allocations` تنها در صورت تنظیم صریح Fail-Open آزاد می‌ماند.
- مسیر `/metrics` نیازمند تعیین یکی از `METRICS_TOKEN` یا قرار گرفتن IP در `METRICS_IP_ALLOWLIST` است و در حالت توکن باید هدر `Authorization: Bearer <token>` ارسال شود؛ خروجی شامل متریک‌های `redis_retry_attempts_total` و `redis_retry_exhausted_total` است که برای پایش پایداری Redis ضروری‌اند.
- مقداردهی متغیر سراسری `METRICS_TOKEN` بر مقدار JSON `IMPORT_TO_SABT_AUTH` (کلید `metrics_token`) اولویت دارد؛ در صورت خالی بودن هر دو، پاسخ `/metrics` با خطای فارسی «متغیر METRICS_TOKEN یا مقدار `metrics_token` داخل JSON `IMPORT_TO_SABT_AUTH` را مقداردهی کنید» قطع می‌شود.
- مسیر پیش‌فرض ذخیرهٔ خروجی‌ها `<ریشهٔ پروژه>/storage/exports` است و در اولین اجرا ساخته می‌شود؛ در صورت نیاز می‌توانید `EXPORT_STORAGE_DIR` را روی مسیر مطمئن دیگری تنظیم کنید.
- برای کوتاه‌کردن زمان تست استریم بزرگ در CI، متغیر `EXPORT_STRESS_ROWS` تعداد ردیف‌های تولیدی را کنترل می‌کند (پیش‌فرض ۱۲٬۰۰۰).
- برای اجرای آزمون یکپارچه‌ی ردیس واقعی، متغیر `LIVE_REDIS_URL` را روی DSN محیط زنده/لوکال تنظیم کنید؛ در غیر این صورت این مسیر جمع‌آوری نمی‌شود.
- اجرای آزمون‌های سخت‌سازی اکنون بدون پرچم‌های اضافی انجام می‌شود: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/hardened_api -q`. حلقهٔ پیش‌فرض asyncio در `pytest.ini` روی `function` ثابت شده و دیگر نیاز به `-o asyncio_default_fixture_loop_scope=function` نیست.
- تمامی سناریوهای HTTP آزمایشی با `httpx.AsyncClient` و `ASGITransport` اجرا می‌شوند تا اخطارهای فرسودگی نسخه‌های آینده (`data=` خام) حذف شوند؛ برای بدنهٔ دلخواه از آرگومان‌های `json=` یا `content=` استفاده کنید.
- لانچر Redis ابتدا باینری محلی را تلاش می‌کند و در صورت نبود، به طور خودکار کانتینر `redis:7` را با Docker اجرا می‌کند؛ با متغیر `REDIS_LAUNCH_MODE` می‌توانید حالت را به `binary`، `docker` یا `skip` محدود کنید. در صورت نبود Docker و باینری، مقدار `skip` باعث ثبت `xfail` مستند در تست‌ها می‌شود.
- نگهبان اخطارهای HTTPX اکنون علاوه بر مسیر موفق POST، مسیر GET `/status` و خطای نوع محتوا را هم بررسی می‌کند تا هیچ اخطار فرسودگی در سناریوهای رایج باقی نماند.

## ابزارهای فاز سوم (Allocation + Outbox)
- اجرای تخصیص اتمیک از خط فرمان: `python -m src.tools.allocation_cli <student_id> <mentor_id> --request-id ... --dry-run`؛ پیام‌ها فارسی و دارای کد خطا هستند.
- دیسپچر Outbox با گزینه‌های `--once` و `--loop`: `python -m src.tools.outbox_dispatcher_cli --database-url sqlite:///allocation.db`.
- پنل گرافیکی Tkinter برای اپراتورها: `python -m src.tools.gui_operator`؛ اجرای Dry-Run روی فایل‌های CSV/JSON در نخ جداگانه انجام می‌شود و وضعیت آخرین رویدادها (PENDING/SENT/FAILED) در لیست فارسی نمایش داده می‌شود.
- خروجی گرفتن از تخصیص‌ها: `python -m src.tools.export_allocations_cli --output allocations.csv --format=csv --bom --crlf`; برای فایل XLSX فرمت را به `xlsx` تغییر دهید. در صورت نیاز به سازگاری کامل با Excel پیام هشدار `EXPORT_BOM_REQUIRED` چاپ می‌شود.

## نصب وابستگی‌های توسعه و pre-commit
- برای فعال‌سازی هوک‌ها، یک‌بار `make init` را اجرا کنید تا وابستگی‌ها از روی `constraints-dev.txt` نصب شوند و `pre-commit` به‌صورت خودکار فعال گردد؛ از این پس `pyupgrade` و `bandit` روی هر کامیت بررسی می‌شوند.

## PYTHONPATH Management
- `setup.py` sets `PYTHONPATH` to the project root and updates `.env` for VS Code integrations.
- Activation scripts export `PYTHONPATH` for shell sessions; re-run them whenever you open a new terminal.
- The doctor script checks whether the project root is present in `PYTHONPATH` and can auto-fix common issues.

## Troubleshooting
- If dependencies are missing, re-run `python setup.py` and select the optional groups you need.
- Use `python -m compileall setup.py scripts/environment_doctor.py` to perform a quick syntax check before commits.
- When Docker is unavailable, install it from docker.com or update your PATH.

## Additional Resources
- `Makefile` provides shortcuts like `make test-quick` for CI-aligned test runs.
- For advanced analytics dashboards, run `streamlit run scripts/dashboard.py` after setup completes.

## Streamlit Dashboards
- Every dashboard module calls `configure_page()` immediately after imports so `st.set_page_config` executes before any other Streamlit command.
- When adding new Streamlit views, follow the same pattern: define a `configure_page()` helper, invoke it at module load, then render the UI in `main()` or a `run()` method.
- Remember that calling `st.set_page_config` after rendering UI elements triggers `StreamlitSetPageConfigMustBeFirstCommandError`.
## Phase 2 Counter Service Operations
- اجرای شمارنده با `python -m src.phase2_counter_service.cli assign-counter <کد_ملی> <جنسیت> <کد_سال>` انجام می‌شود؛ پیام‌های خطا به صورت فارسی و دارای کد ماشینی هستند.
- بک‌فیل روی فایل‌های بسیار بزرگ با دستور `python -m src.phase2_counter_service.cli backfill <csv> --chunk-size 500` به صورت پیش‌فرض خشک اجرا می‌شود؛ برای اعمال نهایی `--apply` را اضافه کنید.
- برای ذخیره خلاصهٔ اجرا در CSV می‌توانید `--stats-csv` را تعیین کنید؛ مسیرهای بدون پسوند یا دارای اسلش پایانی به عنوان پوشه در نظر گرفته شده، در صورت نبود پوشه‌ها به شکل خودکار ساخته می‌شوند و فایل مقصد بعد از نوشتن با پیام فارسی روی استاندارد اوت‌پوت اعلام می‌شود. پرچم‌های `--excel-safe` (محافظت از فرمول)، `--quote-all` (کوت‌گذاری همهٔ ستون‌ها)، `--bom` (افزودن BOM) و `--crlf` (پایان خط ویندوزی) همچنان قابل استفاده هستند. در صورت نیاز به خروجی کاملاً ماشینی می‌توانید `--json-only` را اضافه کنید تا بنر فارسی چاپ نشود و مسیر فایل نهایی به صورت فیلد `stats_csv_path` در JSON بازگردد.
- خروجی خلاصهٔ بک‌فیل در ستون مقدار، مقادیر بولی را به «بله/خیر» بومی‌سازی می‌کند؛ اگر مسیر پوشه تعیین شود فایل با پسوند زمانی و شناسهٔ یکتا ساخته می‌شود و برای بازنویسی فایل موجود باید پرچم `--overwrite` را اضافه کنید.
- اکسپورتر پرومتئوس با `python -m src.phase2_counter_service.cli serve-metrics --oneshot` مقداردهی اولیه شده و گیج سلامت `counter_exporter_health` را به ۱ می‌رساند؛ در حالت بدون `--oneshot` فرایند در فورگراند می‌ماند.
- اپراتورها برای پایش تعاملی می‌توانند `python tools/gui/operator_panel.py` را اجرا کنند؛ این پنل به صورت خودکار در محیط‌های بدون نمایشگر پیام «محیط بدون نمایشگر؛ پنل گرافیکی در دسترس نیست.» را چاپ کرده و بدون خطا خارج می‌شود و چندین پنل همزمان می‌توانند بدون تداخل در هندلرهای لاگ به یک لاگر مشترک متصل شوند.
- اکسپورتر پرومتئوس تنها یک‌بار راه‌اندازی می‌شود، اجرای مجدد `serve-metrics` روی همان پورت بدون تغییر متریک انجام می‌شود و در زمان خاموشی، هر دو گیج `counter_exporter_health` و `counter_metrics_http_started` به ۰ بازنشانی می‌شوند.
- هش کردن PII با متغیر محیطی `PII_HASH_SALT` کنترل می‌شود؛ بدون تعیین آن مقدار پیش‌فرض توسعه استفاده می‌گردد.

## CI Gates و خط فرمان
- `make ci-checks` مجموعه کامل پوشش، Mypy(strict)، Bandit، اعتبارسنجی آرتیفکت‌ها و `post_migration_checks` را اجرا می‌کند و آستانه پوشش ۹۵٪ را enforced می‌نماید.
- `make fault-tests` تنها تست‌های تزریق خطا را اجرا می‌کند تا شاخه‌های مربوط به تعارض پایگاه داده پوشش داده شوند.
- `make static-checks` برای اجرای سریع Mypy و Bandit در جریان توسعه استفاده شود.
- برای اجرای کامل گیت‌های استاتیک در محیط محلی، پیش از فراخوانی `make static-checks` دست‌کم یک‌بار `make init` را اجرا کنید تا Bandit و بسته‌های کمکی نصب شوند.
- برای اجرای تست‌های UI در محیط محلی، در صورت نبود PySide6 یا کتابخانه‌های گرافیکی (libGL/mesa) می‌توانید آن‌ها را نصب کنید یا به پیام اسکیپ «محیط هدلس» اعتماد کنید؛ در حالت نصب‌شده، متغیر `QT_QPA_PLATFORM=offscreen` نیز مسیر اجرای بدون نمایشگر را فراهم می‌کند.
- در محیط‌های بدون نیاز به رابط گرافیکی می‌توانید متغیر `UI_MINIMAL=1` را تنظیم کنید تا صفحات Qt به صورت خودکار غیرفعال شوند و تنها سرویس FastAPI + Swagger در دسترس بماند.
- پس از هر مهاجرت دیتابیس، `make post-migration-checks` روی پایگاه داده موقت اجرا و در صورت هرگونه تغییر در قید UNIQUE یا الگوی شمارنده خطا می‌دهد.
- GitHub Actions تنها از فایل `ci.yml` استفاده می‌کند؛ این پایپ‌لاین روی Python 3.11 و 3.12 اجرا شده و به ترتیب `make fault-tests`, `make static-checks` و در نسخه ۳.۱۱ `make ci-checks` را اجرا می‌کند تا پوشش و اعتبارسنجی آرتیفکت‌ها تضمین شوند.

## سیاست Bandit و حالت UI_MINIMAL
- Bandit فقط خطاهای با شدت Medium/High را مسدود می‌کند؛ یافته‌های Low صرفاً به صورت هشدار فارسی چاپ می‌شوند تا روند CI قطع نشود.
- فایل `.bandit` مسیرهای `tests/`, `venv/`, `.venv/` و `__pycache__/` را حذف می‌کند و در صورت تنظیم `UI_MINIMAL=1` می‌توان با افزودن پرچم `-x src/ui` اسکن UI را موقتاً کنار گذاشت.
- هدف «UI حداقلی با FastAPI+Swagger کافی است» حفظ شده و نبود وابستگی‌های Qt با قرار دادن `UI_MINIMAL=1` در متغیرهای محیطی باعث شکست CI نخواهد شد.
- برای اصلاح خودکار الگوهای رایج (B110/B403/B506/B602/B603) می‌توان `make security-fix` را اجرا کرد؛ پیام‌های افزوده شده به کد برای کاربران فارسی‌زبان خوانا هستند و خطاهای غیرامن با `# nosec` همراه با دلیل فارسی مستندسازی می‌شوند.

## محدودیت‌های عملیاتی و بک‌فیل
- پیشوند جنسیت از SSOT برابر `{0: '373', 1: '357'}` است و هرگونه ناهمخوانی در لاگ‌ها و متریک‌ها گزارش می‌شود.
- حداکثر ظرفیت هر دنباله ۹۹۹۹ است؛ در صورت تجاوز متریک `counter_sequence_exhausted_total` افزایش یافته و خطای `E_COUNTER_EXHAUSTED` صادر می‌گردد.
- بک‌فیل تنها روی ستون‌های `national_id`, `gender`, `year_code` حساب می‌کند و تمام ورودی‌ها پیش از اعمال به کمک NFKC نرمال‌سازی می‌شوند.
- اجرای خشک بک‌فیل از روی حداکثر‌های فعلی در جدول توالی محاسبه می‌کند و تغییری در پایگاه داده ایجاد نمی‌کند.
- در طول بک‌فیل، پیشوند شمارنده برای هر ردیف با جنسیت مقایسه می‌شود؛ در صورت همخوانی، مقدار دنبالهٔ محلی بر اساس حداکثر مقدار موجود به‌روزرسانی می‌شود تا برآورد ظرفیت بعدی دقیق بماند و در صورت ناهماهنگی هش دانش‌آموز ثبت شده و متریک «prefix mismatch» افزایش می‌یابد.
