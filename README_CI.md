# راهنمای اجرای پایپ‌لاین CI

این مخزن برای اطمینان از یکسان بودن نتایج در CI و اجراهای محلی سخت‌گیر شده است. برای آماده‌سازی وابستگی‌ها از دستور واحد زیر استفاده کنید تا وابستگی‌های اصلی و توسعه به‌طور همزمان نصب شوند:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

## اجرای محلی

اسکریپت `tools/run_tests.py` سه گیت اصلی را مشابه CI اجرا می‌کند اما در صورت نبود افزونه‌های اختیاری (مانند `pytest-cov` یا `hypothesis`) با پیام فارسی و حالت جایگزین ادامه می‌دهد:

```bash
python tools/run_tests.py --core
python tools/run_tests.py --golden
python tools/run_tests.py --smoke
```

گزینهٔ `--all` هر سه گیت را پشت سر هم اجرا می‌کند. برای اندازه‌گیری اختیاری p95، متغیرهای محیطی `RUN_P95_CHECK=1` و در صورت نیاز `P95_MS_ALLOCATIONS` را تنظیم کنید.

## CI Notes

- پیش از اجرای `pytest`، متغیر محیطی `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` را تنظیم کنید تا بارگذاری افزونه‌های وابسته به Qt/GL در محیط‌های headless متوقف شود.
- تست‌های Tk در صورت نبود `tkinter` یا امکان ساخت `Tk()` به‌طور خودکار skip می‌شوند؛ خطاهای مربوط به نبود GL نباید اجرا را متوقف کنند.
- در صورت نیاز به فعال‌سازی موقتی پلاگین‌ها، مقدار متغیر را فقط برای آن فراخوانی خاص پاک کنید تا سایر مراحل CI همچنان ایزوله باقی بمانند.

## اجرای CI

Workflow موجود در `.github/workflows/ci.yml` همان گیت‌ها را با سخت‌گیری کامل اجرا می‌کند:

- پوشش خطی با حداقل تعیین‌شده توسط `COVERAGE_MIN` (یا مقدار پیش‌فرض ۸۰) بررسی می‌شود.
- آزمون‌های طلایی با مقایسهٔ بایت‌به‌بایت اجرا می‌گردند.
- روی شاخهٔ `main` تنها مسیرهای دود و انتهابه‌انتها با دستور `pytest -m "smoke and e2e" -q` اجرا می‌شوند.

تمام پیام‌های خطا و خروجی‌ها به‌صورت فارسی و قطعی هستند تا تجربهٔ توسعه‌دهندگان یکسان بماند.

### مثال استفاده از `ci_pytest_runner`

برای پایدارسازی تست‌ها در GitHub Actions می‌توانید از ماتریس دوحالته استفاده کنید:

```yaml
jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        mode: [stub, redis]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Run pytest in ${{ matrix.mode }} mode
        run: python tools/ci_pytest_runner.py --mode ${{ matrix.mode }} --flush-redis auto --probe-mw-order auto
```

این اسکریپت به‌صورت پیش‌فرض Redis واقعی یا stub را پیش از اجرا پاک‌سازی می‌کند، ترتیب `RateLimitMiddleware` و `IdempotencyMiddleware`
را بررسی می‌نماید و در صورت عبور p95 سربار از ۲۰۰ میلی‌ثانیه، خروجی خطای فارسی و قطعی تولید می‌کند. با `--flush-redis yes` پاک‌سازی
اجباری شده و در صورت قطع بودن سرویس با backoff نمایی و خطای فارسی متوقف می‌شود. همچنین می‌توانید با `--p95-samples N` (بین ۳ تا ۱۵)
تعداد نمونه‌برداری برای محاسبهٔ p95 سربار را کنترل کنید تا در محیط‌های کندتر نیز دادهٔ معناداری به‌دست آید.

- برای مسیرهای TLS می‌توانید از `--tls-verify {require,allow-insecure}` و `--tls-ca /path/to/ca.pem` (یا متغیر محیطی `CI_TLS_CA`) استفاده کنید تا اعتبارسنجی گواهی تحت کنترل بماند؛ شکست‌ها با پیام `❶ TLS_VERIFY_FAILED` اعلام می‌شوند.
- برای بررسی دقیق‌تر لاگ‌ها، گزینهٔ `--redact-urls no` مقادیر را بدون افشای گذرواژه (اما با ماسک کاراکترهای حساس) چاپ می‌کند.
- در صورت تنظیم `CI_TLS_HARNESS=1`، هارنس TLS در مسیر `tests/ci/certs/` فعال می‌شود و سناریوهای rediss:// بدون وابستگی خارجی آزمایش می‌گردند.
