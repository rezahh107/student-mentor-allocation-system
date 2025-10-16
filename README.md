# SmartAllocPY Environment Guide

## Quick Start
- Run `python setup.py` to install dependencies, set `PYTHONPATH`, configure VS Code, and generate `activate` scripts.
- Use `activate.bat` (Windows) or `source ./activate.sh` (macOS/Linux) before working in a new shell.
- Launch diagnostics with `python scripts/environment_doctor.py` to validate the environment and apply optional fixes.

<!--dev-quick-start:start-->

## Quick Start (Dev)

### پیش‌نیازها
- Python 3.11
- (اختیاری) Docker Compose برای Redis/Postgres

### نصب
```bash
pip install -r requirements.txt
cp -n .env.example .env.dev
export SIGNING_KEY_HEX=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

### دیتابیس‌ها (اختیاری)
```bash
docker compose -f docker-compose.dev.yml up -d
```

### اجرا
```bash
uvicorn main:app --host 127.0.0.1 --port 25119 --env-file .env.dev
```

### اسموک‌تست
```bash
METRICS_TOKEN=dev-metrics scripts/smoke.sh
```

<!--dev-quick-start:end-->

## FastAPI Hardened Service Configuration
- `REDIS_NAMESPACE` و `REDIS_URL` برای تفکیک فضای کلید و اتصال به Redis استفاده می‌شوند؛ در CI مقدار `REDIS_URL` از سرویس `redis:7` تزریق می‌گردد.
- سیاست Retry Redis از طریق متغیرهای `REDIS_MAX_RETRIES` (پیش‌فرض ۳)، `REDIS_BASE_DELAY_MS`، `REDIS_MAX_DELAY_MS` و `REDIS_JITTER_MS` قابل تنظیم است.
- برای فعال‌سازی Fail-Open عمومی می‌توانید `RATE_LIMIT_FAIL_OPEN=1` را تنظیم کنید؛ GET ها در صورت خطا همیشه Fail-Open می‌شوند و `POST /allocations` تنها در صورت تنظیم صریح Fail-Open آزاد می‌ماند.
- مسیر `/metrics` نیازمند تعیین یکی از `METRICS_TOKEN` یا قرار گرفتن IP در `METRICS_IP_ALLOWLIST` است؛ خروجی شامل متریک‌های `redis_retry_attempts_total` و `redis_retry_exhausted_total` است که برای پایش پایداری Redis ضروری‌اند.
- اجرای آزمون‌های سخت‌سازی اکنون بدون پرچم‌های اضافی انجام می‌شود: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin tests/hardened_api -q`. حلقهٔ پیش‌فرض asyncio در `pytest.ini` روی `function` ثابت شده و دیگر نیاز به `-o asyncio_default_fixture_loop_scope=function` نیست.
- تمامی سناریوهای HTTP آزمایشی با `httpx.AsyncClient` و `ASGITransport` اجرا می‌شوند تا اخطارهای فرسودگی نسخه‌های آینده (`data=` خام) حذف شوند؛ برای بدنهٔ دلخواه از آرگومان‌های `json=` یا `content=` استفاده کنید.
- لانچر Redis ابتدا باینری محلی را تلاش می‌کند و در صورت نبود، به طور خودکار کانتینر `redis:7` را با Docker اجرا می‌کند؛ با متغیر `REDIS_LAUNCH_MODE` می‌توانید حالت را به `binary`، `docker` یا `skip` محدود کنید. در صورت نبود Docker و باینری، مقدار `skip` باعث ثبت `xfail` مستند در تست‌ها می‌شود.
- نگهبان اخطارهای HTTPX اکنون علاوه بر مسیر موفق POST، مسیر GET `/status` و خطای نوع محتوا را هم بررسی می‌کند تا هیچ اخطار فرسودگی در سناریوهای رایج باقی نماند.

## ابزارهای فاز سوم (Allocation + Outbox)
- اجرای تخصیص اتمیک از خط فرمان: `python -m src.tools.allocation_cli <student_id> <mentor_id> --request-id ... --dry-run`؛ پیام‌ها فارسی و دارای کد خطا هستند.
- دیسپچر Outbox با گزینه‌های `--once` و `--loop`: `python -m src.tools.outbox_dispatcher_cli --database-url sqlite:///allocation.db`.
- پنل گرافیکی Tkinter برای اپراتورها: `python -m src.tools.gui_operator`؛ اجرای Dry-Run روی فایل‌های CSV/JSON در نخ جداگانه انجام می‌شود و وضعیت آخرین رویدادها (PENDING/SENT/FAILED) در لیست فارسی نمایش داده می‌شود.
- خروجی گرفتن از تخصیص‌ها: `python -m src.tools.export_allocations_cli --output allocations.csv --format=csv --bom --crlf`; برای فایل XLSX فرمت را به `xlsx` تغییر دهید. در صورت نیاز به سازگاری کامل با Excel پیام هشدار `EXPORT_BOM_REQUIRED` چاپ می‌شود.

## نصب وابستگی‌های توسعه و pre-commit
- برای فعال‌سازی هوک‌ها، یک‌بار `pip install -r requirements-dev.txt` و سپس `pre-commit install` را اجرا کنید؛ از این پس `pyupgrade` و `bandit` روی هر کامیت بررسی می‌شوند.

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
- برای اجرای کامل گیت‌های استاتیک در محیط محلی، پیش از فراخوانی `make static-checks` دست‌کم یک‌بار `pip install -r requirements-dev.txt` را اجرا کنید تا Bandit و بسته‌های کمکی نصب شوند.
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
