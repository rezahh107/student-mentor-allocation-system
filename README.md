# SmartAllocPY Environment Guide

## Quick Start
- Run `python setup.py` to install dependencies, set `PYTHONPATH`, configure VS Code, and generate `activate` scripts.
- Use `activate.bat` (Windows) or `source ./activate.sh` (macOS/Linux) before working in a new shell.
- Launch diagnostics with `python scripts/environment_doctor.py` to validate the environment and apply optional fixes.

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
- اکسپورتر پرومتئوس با `python -m src.phase2_counter_service.cli serve-metrics --oneshot` مقداردهی اولیه شده و گیج سلامت `counter_exporter_health` را به ۱ می‌رساند؛ در حالت بدون `--oneshot` فرایند در فورگراند می‌ماند.
- هش کردن PII با متغیر محیطی `PII_HASH_SALT` کنترل می‌شود؛ بدون تعیین آن مقدار پیش‌فرض توسعه استفاده می‌گردد.

## CI Gates و خط فرمان
- `make ci-checks` مجموعه کامل پوشش، Mypy(strict)، Bandit، اعتبارسنجی آرتیفکت‌ها و `post_migration_checks` را اجرا می‌کند و آستانه پوشش ۹۵٪ را enforced می‌نماید.
- `make fault-tests` تنها تست‌های تزریق خطا را اجرا می‌کند تا شاخه‌های مربوط به تعارض پایگاه داده پوشش داده شوند.
- `make static-checks` برای اجرای سریع Mypy و Bandit در جریان توسعه استفاده شود.
- پس از هر مهاجرت دیتابیس، `make post-migration-checks` روی پایگاه داده موقت اجرا و در صورت هرگونه تغییر در قید UNIQUE یا الگوی شمارنده خطا می‌دهد.

## محدودیت‌های عملیاتی و بک‌فیل
- پیشوند جنسیت از SSOT برابر `{0: '373', 1: '357'}` است و هرگونه ناهمخوانی در لاگ‌ها و متریک‌ها گزارش می‌شود.
- حداکثر ظرفیت هر دنباله ۹۹۹۹ است؛ در صورت تجاوز متریک `counter_sequence_exhausted_total` افزایش یافته و خطای `E_COUNTER_EXHAUSTED` صادر می‌گردد.
- بک‌فیل تنها روی ستون‌های `national_id`, `gender`, `year_code` حساب می‌کند و تمام ورودی‌ها پیش از اعمال به کمک NFKC نرمال‌سازی می‌شوند.
- اجرای خشک بک‌فیل از روی حداکثر‌های فعلی در جدول توالی محاسبه می‌کند و تغییری در پایگاه داده ایجاد نمی‌کند.
