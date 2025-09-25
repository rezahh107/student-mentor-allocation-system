# سخت‌سازی امنیت و پوشش تست Legacy

این سند نحوهٔ اجرای دروازه‌های امنیتی و پوشش تست را با پیام‌های فارسی توضیح می‌دهد.

## گام‌های CI

1. `make static-checks` → اجرای تست‌های استاتیک و بررسی‌های Mypy.
2. `make ci-checks` → اجرای پوشش ماژول `src/phase2_counter_service` با فرمانی که `--cov-fail-under=$(COV_MIN)` را بر اساس متغیر محیطی `COV_MIN` (پیش‌فرض ۹۵) تنظیم می‌کند تا خطای «No data to report» رفع شده و آستانهٔ تعیین‌شده تضمین شود.
3. `COV_MIN=95 PYTEST_ARGS="-q --maxfail=1 -p pytest_cov --cov=src --cov-report=term --cov-report=xml --cov-report=html" make test-coverage` → اجرای تست‌های legacy با خلاصهٔ فارسی و تولید `htmlcov/`. می‌توانید مقدار `COV_MIN` را متناسب با نیاز خود (مثلاً ۹۷) تغییر دهید.
4. `make security-scan` → اجرای Bandit با پیام‌های دترمینیستیک فارسی و تولید `reports/bandit.json`.

در CI، خروجی HTML پوشش با نام `htmlcov-<python>` و گزارش امنیتی با نام `bandit-json` به‌صورت artifact آپلود می‌شود.

## اعتماد به تجزیه‌گر XML

- درگاه پوشش ابتدا تلاش می‌کند `defusedxml.ElementTree` را بارگذاری کند تا از حملات XXE جلوگیری شود.
- اگر بستهٔ `defusedxml` در محیط (مثلاً در حالت آفلاین) موجود نباشد، با پیام فارسی `SEC_SAFE_XML_FALLBACK` اعلام می‌شود که از `xml.etree.ElementTree` استاندارد صرفاً برای فایل محلی `coverage.xml` استفاده خواهد شد.
- این فایل توسط pytest روی همان ماشین تولید می‌شود؛ بنابراین مرز اعتماد حفظ شده و Bandit با شناسهٔ B314 علامت‌گذاری نمی‌کند.

## متغیرهای پیکربندی

- `COV_MIN` (پیش‌فرض 95) → آستانهٔ پوشش تست. مقادیر خالی، `null`، `0`، ارقام فارسی/عربی یا متن دارای نویسه‌های صفرعرض رسیدگی و نرمال‌سازی می‌شوند.
- `LEGACY_TEST_PATTERN` (پیش‌فرض `tests/legacy/test_*.py`) → مسیر تست‌های legacy. مقدار خالی یا `0` به مقدار پیش‌فرض برمی‌گردد.
- `BANDIT_FAIL_LEVEL` (پیش‌فرض `MEDIUM`) → سطح شدت مجاز Bandit. مقادیر معتبر `{LOW, MEDIUM, HIGH}` هستند؛ مقدار نامعتبر به `MEDIUM` تبدیل و با کد `SEC_BANDIT_LEVEL_DEFAULT` اعلام می‌شود.
- `PYTEST_ARGS` → رشتهٔ quoted برای عبور آرگومان‌های اضافه به pytest در درگاه پوشش.
- `LEGACY_TARGETS` → مسیر یا الگوی دلخواه برای override هدف تست‌های legacy.

برای اجرا در محیط محلی:

```bash
pip install -r requirements.txt -r requirements-dev.txt bandit pytest-cov
make static-checks
make ci-checks
COV_MIN=95 PYTEST_ARGS="-q --maxfail=1 -p pytest_cov --cov=src --cov-report=term --cov-report=xml --cov-report=html" make test-coverage
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/legacy -k "not gui"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/export -k hygiene
make security-scan
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/gui/test_gui_operator_smoke.py || true
```

## تشخیص محیط Headless

تست‌های GUI (از جمله `tests/gui/test_gui_operator_smoke.py`) در نبود متغیر `DISPLAY` یا خطای Tk با پیام `GUI_HEADLESS_SKIPPED` به‌صورت خودکار skip می‌شوند. در سرورهای headless مقدار `UI_MINIMAL=1` نیز می‌تواند جهت عبور از تست‌های PySide استفاده شود.

## طلایی‌های Excel

- تست‌های `tests/export/test_csv_excel_hygiene.py` و `tests/export/test_xlsx_excel_hygiene.py` خروجی‌ها را با فایل‌های طلایی در `tests/golden/export/` مقایسه می‌کنند تا BOM، CRLF، quoting و حفظ ارقام فارسی تضمین شود.
- برای به‌روزرسانی طلایی‌ها کافیست exporterها را اجرا کرده و محتوای جدید را در همان مسیر جایگزین کنید؛ فرمت فایل‌ها UTF-8 است.

## عیب‌یابی

- **`SEC_BANDIT_NOT_INSTALLED`** → بستهٔ Bandit نصب نشده است؛ با `pip install bandit` رفع می‌شود.
- **`SEC_BANDIT_FINDINGS`** → یافته‌های شدت `BANDIT_FAIL_LEVEL` یا بالاتر وجود دارد؛ فایل `reports/bandit.json` را بررسی کنید.
- **`COV_BELOW_THRESHOLD`** → پوشش تست کمتر از `COV_MIN` است؛ تست‌های legacy را گسترش دهید و دوباره `make test-coverage` را اجرا کنید.
- **`PYTEST_COV_MISSING`** → بستهٔ `pytest-cov` نصب نشده یا بارگذاری افزونه با خطای `PluginValidationError` مواجه شده است؛ با `pip install pytest-cov` آن را نصب کرده و دوباره فرمان را اجرا کنید.
- **`COV_NO_TESTS`** → هیچ تستی با الگوی legacy پیدا نشد؛ مسیر الگو یا نام فایل‌ها را بازبینی کنید.
- **`COV_XML_MISSING`** → فایل `coverage.xml` تولید نشده؛ اجرای pytest شکست خورده است (خروجی stderr را بررسی کنید).

تمام پیام‌های کاربرمحور فارسی بوده و کد خطاهای ثابت دارند تا در مانیتورینگ و Excel راحت پالایش شوند.
