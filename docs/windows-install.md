# Windows installation guide

این نسخهٔ به‌روزشدهٔ راهنما مسیر **خودترمیم‌شونده** برای کاربران Windows 10/11 (PowerShell 7+) فراهم می‌کند تا سامانهٔ ImportToSabt را بدون خطا اجرا کنند. تمام مراحل از پیش‌نیازها تا تست پایانی در اسکریپت `scripts/win/install_and_run.ps1` مجتمع شده است و هر فرمان خروجی **[PASS]/[FIXED]/[SKIP]/[FAIL]** چاپ می‌کند تا خطاها زود تشخیص داده شوند.

> ⚠️ **هشدار بیلد لوکال:** نسخهٔ فعلی فقط برای توسعه است؛ میان‌افزارهای امنیتی Auth و RateLimit و همچنین RBAC از برنامه حذف شده‌اند. برای استقرار تولیدی باید این مؤلفه‌ها را از شاخهٔ اصلی بازگردانی کنید.

## 1. پیش‌نیازهای سیستم

1. **PowerShell 7+** را با [Microsoft Store](https://apps.microsoft.com) نصب یا به‌روزرسانی کنید.
2. **Windows Terminal** را با پروفایل PowerShell 7 باز کرده و مطمئن شوید که می‌توانید فرمان‌های زیر را اجرا کنید (بدون خطا و بدون پیام `[FAIL]`):

   ```powershell
   chcp 65001
   pwsh -NoLogo -Command "$PSVersionTable.PSVersion"
   ```

3. ریپو را در مسیری کوتاه (مثلاً `C:\Dev\student-mentor-allocation-system`) کلون کنید تا طول مسیر بیش از حد نشود.

## 2. اجرای اسکریپت خودترمیمی

در ریشهٔ ریپو، PowerShell 7 را باز و دستورات زیر را **به‌ترتیب** اجرا کنید. هر بخش را می‌توان جداگانه اجرا/تکرار کرد؛ اسکریپت idempotent است و اجرای دوباره فقط وضعیت را تأیید می‌کند.

```powershell
Set-Location C:\Dev\student-mentor-allocation-system
pwsh -NoLogo -ExecutionPolicy Bypass -File .\scripts\win\install_and_run.ps1
```

### خروجی مورد انتظار (خلاصه)

| فاز | نمونهٔ خروجی | هدف |
| --- | --- | --- |
| پوسته | `[PASS] repo-root::Repository root set to ...` | اطمینان از مسیر صحیح |
| سیاست اجرا | `[FIXED] execution-policy::ExecutionPolicy set to RemoteSigned` | فعال‌سازی اسکریپت‌ها بدون اخطار |
| مفسر Python | `[PASS] python-discovery::Using Python from py launcher: Python 3.11.12` | جلوگیری از خطای «python3.11 executable not found» |
| نصب وابستگی‌ها | `[PASS] pip-install::Editable install with dev extras completed` | رفع خطای `ModuleNotFoundError: No module named 'sma'` |
| اعتبارسنجی env | `[PASS] dotenv::AppConfig instantiated successfully` | تصحیح کلیدهای تو در تو (`IMPORT_TO_SABT_*__*`) |
| سرویس‌ها | `[FIXED] services::Started container 'sma-dev-redis-<RUN_ID>'...` یا `[SKIP] services::Docker CLI not available...` | رفع خطاهای اتصال Redis/PostgreSQL |
| اجرا | `[PASS] uvicorn::Uvicorn listening on port ...` سپس `/readyz → HTTP 200` | تضمین سلامتی endpoint صحیح |
| امنیت | **در بیلد محلی انتظار می‌رود `/metrics` بدون توکن در دسترس باشد؛** پس از بازگردانی امنیت باید `/metrics (no token) → HTTP 403` و `/metrics (with token) → HTTP 200` شود. | تأیید توکن و جلوگیری از دسترسی عمومی |

> **توجه:** اگر `ENVIRONMENT=production` در `.env` تنظیم شده باشد و `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` باشد، اسکریپت با پیام فارسی/انگلیسی متوقف می‌شود تا از انتشار اسناد در محیط تولید جلوگیری شود.

## 3. چه مواردی کنترل می‌شود؟

اسکریپت ۸ گام اصلی دارد؛ هر گام با لاگ‌های وضعیت و بازرسی‌های درون‌خطی همراه است:

1. **تنظیم پوسته:** `Set-StrictMode`, `chcp 65001`, تنظیم خروجی UTF-8.
2. **سیاست اجرا:** تبدیل ExecutionPolicy کاربر جاری به RemoteSigned (در صورت نیاز).
3. **پیش‌نیازهای ویژوال C++:** بررسی/نصب `Microsoft.VisualStudio.2022.BuildTools` با `winget`.
4. **Python 3.11.12:** جست‌وجوی `py -3.11`, مسیر `pyenv-win`, یا `python.exe` و رد هر نسخهٔ خارج از بازهٔ `>=3.11,<3.12`.
5. **محیط مجازی + وابستگی‌ها:** ساخت `.venv`, ارتقای `pip`, نصب `pip install -e .[dev]`, حذف `uvloop` در صورت وجود، اجرای `pip check`، و اعتبارسنجی `import sma, jinja2`.
6. **تنظیم فایل `.env`:** در صورت عدم وجود، کپی از `.env.example`, سپس تضمین کلیدهای تو در توی حیاتی (`IMPORT_TO_SABT_REDIS__DSN`, `...DATABASE__DSN`, `...AUTH__SERVICE_TOKEN`, `...SECURITY__PUBLIC_DOCS`) و فعال‌سازی صریح `METRICS_ENDPOINT_ENABLED=true` تا مسیر `/metrics` بدون نیاز به توکن در محیط لوکال پاسخ‌گو باشد؛ در پایان متغیرهای فرآیندی `IMPORT_TO_SABT_*` که ممکن است از تلاش‌های قبلی باقی مانده باشند پاک‌سازی می‌شوند.
7. **سرویس‌های داده:** تست درگاه‌های 6379/5432. اگر بسته باشند و Docker موجود باشد، کانتینرهای `sma-dev-redis-<RUN_ID>` و `sma-dev-postgres-<RUN_ID>` با `--restart unless-stopped` راه‌اندازی می‌شوند؛ در غیر این صورت `DEVMODE=1` برای استفاده از Fakeredis/SQLite تنظیم می‌شود.
8. **اجرای برنامه و پروب‌ها:** اجرای `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --factory`, سپس درخواست‌های `/readyz`→`/healthz`→`/health`, `/docs`, و `/metrics` (در صورت فعال بودن `METRICS_ENDPOINT_ENABLED=true` و بدون نیاز به توکن).

## 4. نقشهٔ خطاهای تاریخی (reports/selfheal-run.json)

| شناسهٔ خطای تاریخی | توضیح مشکل پیشین | گارد فعلی |
| --- | --- | --- |
| `python3.11 executable not found` | پوستهٔ قبلی نسخهٔ صحیح Python را پیدا نمی‌کرد | گام 4 نسخهٔ دقیق `Python 3.11.12` را جست‌وجو کرده و در غیر این صورت متوقف می‌شود |
| «pyenv/apt confusion» | تضاد بین نصب‌های `pyenv` و سیستم | اولویت با `py -3.11` است، سپس مسیر `pyenv-win` و در نهایت `python.exe`; هر گزینه با پیام صریح `[PASS]/[FAIL]` گزارش می‌شود |
| `ModuleNotFoundError: No module named 'sma'` | نصب ناقص پکیج | نصب editable (`pip install -e .[dev]`) + اضافه شدن `jinja2` به dev extras |
| `ValidationError: redis/database/auth fields required` | کلیدهای تو در تو با `_` عادی اشتباه شده بودند | `Ensure-Var` تمام کلیدها را با ساختار `SECTION__FIELD` تصحیح می‌کند |
| «dotenv path» | بارگذاری `.env` در پوسته‌های غیرتعاملی انجام نمی‌شد | `main.py` اکنون `load_dotenv(dotenv_path='.env', override=True)` فراخوانی می‌کند |
| `missing jinja2 dependency` | uvicorn بدون Jinja2 اجرا می‌شد | dev extras شامل `jinja2` است و اسکریپت صحت `import jinja2` را بررسی می‌کند |
| «missing/invalid signing keys» | مقادیر قبلی `IMPORT_TO_SABT_*` در محیط فرآیند باقی می‌ماند و گارد امضا را خراب می‌کرد | `Clear-StaleImportEnv` تمام متغیرهای فرآیند را پاک می‌کند تا فقط `.env` مرجع باشد؛ مقداردهی پیش‌فرض توکن/سرویس نیز انجام می‌شود |
| `/health` → 401 | آدرس اشتباه استفاده می‌شد | حلقهٔ پروب ابتدا `/readyz`، سپس `/healthz` و در نهایت `/health` را بررسی می‌کند تا از کد 200 مطمئن شود |
| `/docs` → 401 | `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS` تنظیم نشده بود | مقدار پیش‌فرض `true` تزریق می‌شود و اسکریپت وضعیت 200 را بررسی می‌کند |
| `/metrics` غیرفعال است | متغیر `METRICS_ENDPOINT_ENABLED` تنظیم نشده | در بیلد محلی باید `METRICS_ENDPOINT_ENABLED=true` باشد تا مسیر فعال شود؛ در حالت تولید باید Auth بازگردانی شود |

> اجرای مجدد اسکریپت باید فقط `[PASS]`‌ها را چاپ کند؛ اگر `[FIXED]` ظاهر شود یعنی مشکلی برطرف شده است و می‌توانید فرمان را دوباره برای اطمینان اجرا کنید.

## 5. پس از اجرا

1. مرورگر را به `http://127.0.0.1:8000/docs` باز کنید (فقط اگر در `.env` مقدار `IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true` است).
2. در بیلد محلی فقط زمانی `/metrics` پاسخ می‌دهد که `METRICS_ENDPOINT_ENABLED=true` باشد و بدون نیاز به هدر در دسترس است؛ برای تست تولیدی باید Guard احراز هویت را بازگردانی کرده و هدر `Authorization: Bearer <METRICS_TOKEN>` ارسال کنید.
3. برای توقف برنامه، از همان پنجرهٔ PowerShell که اسکریپت را اجرا کرده‌اید استفاده کنید؛ اسکریپت uvicorn را در انتها متوقف می‌کند و فایل لاگ در `tmp\win-run\uvicorn.log` ذخیره می‌شود.

## 6. اشکال‌زدایی

* اگر خروجی `[FAIL] prerequisites::winget is required` مشاهده شد، آخرین نسخهٔ `App Installer` را نصب کرده و دوباره اسکریپت را اجرا کنید.
* پیام `Expected Python 3.11.12` یعنی نسخهٔ دیگری روی سیستم فعال است. `py -0` را اجرا کرده و سایر نسخه‌ها را حذف یا غیرفعال کنید.
* اگر Docker نصب نیست و اسکریپت `DEVMODE=1` را فعال کرد، مطمئن شوید که اتصال Redis/PostgreSQL قبلی باز نیست؛ در غیر این صورت پورت‌ها را آزاد کنید یا Docker Desktop را نصب کنید.
* برای بررسی نتیجهٔ پروب‌ها به `tmp\win-run\uvicorn.log` یا خروجی `[FAIL]` مراجعه کنید؛ متن پاسخ (اولین ۱۰۰ کاراکتر) در همان پیام چاپ می‌شود.

## 7. CI & Verification

برای اطمینان از سلامت خودکار، مخزن دارای گردش‌کار GitHub Actions به نام **Windows Smoke** است که روی `windows-latest` اجرا می‌شود.

1. قبل از اجرای اسکریپت، گام پاک‌سازی `tools/win/clear_state.ps1 -Force -RunId <RUN_ID>` اجرا می‌شود تا فقط کانتینرهایی که با همان پسوند ساخته شده‌اند حذف شوند. مقدار `RUN_ID` معمولاً همان `github.run_id` است و از تداخل اجرای موازی جلوگیری می‌کند.
2. اسکریپت اصلی با حالت بدون‌تعامل اجرا می‌شود:

   ```powershell
  pwsh -NoLogo -ExecutionPolicy Bypass -File .\scripts\win\install_and_run.ps1 -Ci -Port 8000 -RunId $env:GITHUB_RUN_ID
  ```

  * در حالت `-Ci`، تایم‌اوت‌ها کوتاه‌تر می‌شوند، تمام مارکرها به صورت `reports/ci/installer.ndjson` ذخیره می‌شوند، نتیجهٔ پروب‌ها در `reports/ci/probes.json` ثبت شده و تخلیهٔ متغیرها در `reports/ci/env_dump.json` انجام می‌شود.
  * هر سطر خروجی در CI با `[PASS] step::detail`، `[FIXED] step::detail`، `[SKIP] step::detail` یا `[FAIL] step::detail` شروع می‌شود. ابزار `tools/ci/parse_markers.py` خروجی را بررسی و در صورت مشاهدهٔ هر `[FAIL]` مرحلهٔ CI را متوقف می‌کند.
  * سوئیچ جدید `-RunId` نام کانتینرهای Docker را به صورت `sma-dev-redis-<RUN_ID>` و `sma-dev-postgres-<RUN_ID>` می‌سازد؛ به این ترتیب اجرای هم‌زمان چند Job بدون تصادم ادامه می‌یابد و اجرای مجدد با همان مقدار فقط وضعیت فعلی را تأیید می‌کند.
  * برای فعال‌سازی `/metrics` در این سناریو، تنظیم `METRICS_ENDPOINT_ENABLED=true` کفایت می‌کند و نیاز به عبور توکن وجود ندارد؛ پارامتر اختیاری `-MetricsToken` صرفاً جهت سازگاری با اسکریپت‌های قدیمی باقی مانده است.

3. پس از اتمام اسکریپت، گردش‌کار دو تست Pytest را اجرا می‌کند تا گاردهای دامنه‌ای سالم بمانند:

   ```powershell
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/middleware/test_order.py
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/excel/test_safe_export.py
   ```

  * تست `tests/middleware/test_order.py::test_middleware_order_chain` در نسخهٔ تولید آرایهٔ `app.user_middleware` را بررسی می‌کند تا ترتیب `RateLimit → Idempotency → Auth` حفظ شود؛ در بیلد محلی میان‌افزارها حذف شده‌اند و این تست باید پس از بازگردانی امنیت فعال شود.
   * تست `tests/excel/test_safe_export.py::test_excel_export_guards_formula_and_utf8` دادهٔ فارسی و مقادیر خطرناک را خروجی می‌گیرد و مطمئن می‌شود که نگهبان فرمول (`'`)، حذف نویسه‌های صفرعرض و نرمال‌سازی اعداد/نقل‌قول‌ها برقرار است.

4. آرتیفکت‌های زیر در پایان Job آپلود می‌شوند:

   - `reports/ci/installer.ndjson`, `reports/ci/probes.json`, `reports/ci/env_dump.json`
   - `reports/ci/pip-freeze.txt`
   - `tmp/win-run/uvicorn.log`

5. برای اجرای محلی همان سناریوی CI، مراحل زیر را دنبال کنید:

   ```powershell
   $runId = (Get-Date -Format 'yyyyMMddHHmmss')
   pwsh -NoLogo -ExecutionPolicy Bypass -File .\tools\win\clear_state.ps1 -Force -RunId $runId
   $log = .\reports\ci\installer.log
  $output = & .\scripts\win\install_and_run.ps1 -Ci -Port 8000 -RunId $runId 2>&1 | Tee-Object -FilePath $log
   python .\tools\ci\parse_markers.py $log --json .\reports\ci\markers.json
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/middleware/test_order.py
   PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/excel/test_safe_export.py
   ```

   اگر خروجی ابزار پارس‌کننده بدون خطا پایان یافت و `/readyz`, `/docs`, `/metrics` مطابق جدول فوق بودند، سناریوی کامل تأیید شده است.

با دنبال‌کردن این مراحل، کاربر تازه‌وارد در Windows می‌تواند اسکریپت را خط‌به‌خط اجرا کرده و به خروجی سالم `/readyz`, `/docs`, `/metrics` برسد؛ تمام خطاهای ثبت‌شده در `reports/selfheal-run.json` پیش از رخداد شناسایی و خنثی می‌شوند.
