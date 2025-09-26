# سخت‌سازی API تخصیص دانش‌آموز به منتور

این سند نحوه استفاده از نسخه تقویت‌شدهٔ API را توضیح می‌دهد. سرویس جدید روی FastAPI 3.11 پیاده‌سازی شده و لایه‌های احراز هویت، اعتبارسنجی، رصدپذیری و محدودسازی نرخ را فراهم می‌کند.

## مسیرها

| مسیر | متد | توضیح | دامنهٔ موردنیاز |
|------|-----|--------|------------------|
| `/allocations` | POST | ثبت تخصیص اتمیک از طریق سرویس Phase4 | `alloc:write` |
| `/status` | GET | وضعیت سلامت سرویس | `alloc:read` |
| `/metrics` | GET | متریک‌های Prometheus | توکن متریک اختصاصی + IP مجاز |
| `/admin` | GET | رابط مدیریتی سبک برای اپراتورها | هدر `X-Admin-Token` |

## هدرهای حمایتی

| هدر | توضیح | وضعیت |
|------|-------|--------|
| `Authorization: Bearer <token>` | توکن JWT HS256 یا توکن ایستا | الزامی مگر اینکه `X-API-Key` ارائه شود |
| `X-API-Key` | کلید مصرف‌کننده (ذخیره‌شده به‌صورت هش) | جایگزین هدر Authorization |
| `Content-Type` | باید دقیقاً `application/json; charset=utf-8` باشد | الزامی برای POST |
| `X-Request-ID` | شناسهٔ درخواست در صورت ارسال از کلاینت | اختیاری (در صورت عدم ارسال تولید می‌شود) |
| `Idempotency-Key` | کلید ایدمپوتنسی (الزامی برای رفتار تکرارپذیر) | اختیاری اما توصیه‌شده |
| `X-Admin-Token` | توکن عملیات برای مسیرهای `/admin/*` | الزامی برای داشبورد |

## الزامات بدنهٔ درخواست `/allocations`

```jsonc
{
  "student_id": "0012345679",           // ۱۰ رقم معتبر با چک‌سام (digits فارسی/عربی پشتیبانی می‌شود)
  "mentor_id": 128,                      // عدد صحیح
  "reg_center": 1,                       // فقط مقادیر {0,1,2}
  "reg_status": 1,                       // فقط مقادیر {0,1,3}
  "gender": 0,                           // فقط مقادیر {0,1}
  "payload": {},                         // دیکشنری JSON
  "metadata": {},                        // دیکشنری JSON؛ فیلدهای دامنه به آن اضافه می‌شود
  "year_code": "23"                     // ۲ یا ۴ رقم (اختیاری)
}
```

## پاسخ موفق نمونه

```json
{
  "allocationId": 1,
  "allocationCode": "2300000001",
  "mentorId": 128,
  "status": "OK",
  "message": "عملیات موفق بود",
  "errorCode": null,
  "idempotencyKey": "idem-0012345679-128",
  "outboxEventId": "evt-1",
  "dryRun": false,
  "correlationId": "8e9d3d60-cc02-4e8f-9f4c-6c3d1e80f0fb"
}
```

## خطاهای استاندارد

تمام خطاها با ساختار زیر بازگردانده می‌شوند:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message_fa": "پیام قابل‌خواندن فارسی",
    "correlation_id": "..."
  },
  "details": [
    {"field": "gender", "message": "مقدار فیلد gender مجاز نیست"}
  ]
}
```

کدهای ممکن:

- `AUTH_REQUIRED`
- `INVALID_TOKEN`
- `ROLE_DENIED`
- `RATE_LIMIT_EXCEEDED`
- `VALIDATION_ERROR`
- `CONFLICT`
- `INTERNAL`

## رابط مدیریتی `/admin`

- برای دسترسی باید هدر `X-Admin-Token` با مقدار دقیقاً مطابق مقدار تنظیمات (`ALLOC_API_ADMIN_TOKEN`) ارسال شود.
- صفحهٔ HTML بدون وابستگی به فرانت‌اند‌های سنگین تولید شده، با `dir="rtl"`، برچسب‌های ARIA و حلقهٔ تمرکز مشخص در محیط‌های Headless نیز قابل‌تست است.
- عملیات پشتیبانی‌شده:
  - `GET /admin/api-keys`: فهرست کلیدها با متادیتای `last_used_at`، `disabled_at` و `rotation_hint`.
  - `POST /admin/api-keys`: ساخت کلید جدید (پاسخ شامل مقدار کلید یکبارمصرف است).
  - `POST /admin/api-keys/{id}/rotate`: چرخش امن کلید (کلید قدیمی بلافاصله غیرفعال می‌شود).
  - `POST /admin/api-keys/{id}/disable`: غیرفعالسازی نرم با ثبت `disabled_at`.
- همهٔ پاسخ‌ها شامل `correlation_id` و پیام فارسی قطعی هستند و خطاها به فرمت استاندارد باز می‌گردند.
- داشبورد شامل کارت‌های آماری فقط‌خواندنی برای شمارنده‌های محدودیت نرخ، وضعیت کش ایدمپوتنسی، زمان کارکرد سرویس و شناسهٔ همبستگی جاری است.
- برای اسکریپت و استایل از nonce تصادفی و هدر `Content-Security-Policy` استفاده می‌شود تا اجرای کد تزریقی مسدود شود.

## ماژول Excel (`src/api/excel_io.py`)

- تابع `sanitize_cell` تمامی ورودی‌ها را NFKC، تبدیل ارقام فارسی/عربی به لاتین، حذف نویسه‌های صفرعرض و جلوگیری از حملات فرمولی (پیشوند `'` برای مقادیر شروع‌شونده با `=`, `+`, `-`, `@`) می‌کند.
- `write_csv` خروجی UTF-8-SIG (به‌همراه BOM) تولید می‌کند تا در Excel فارسی بدون خرابی نمایش داده شود و از استریم استفاده می‌کند؛ نیازی به نگه داشتن کل فایل در حافظه نیست.
- `iter_csv_rows` و `iter_xlsx_rows` خواندن استریمی برای فایل‌های حجیم (۱۰۰هزار ردیف به بالا) را فراهم می‌کنند؛ نسخهٔ XLSX تنها در صورت نصب ماژول اختیاری `openpyxl` فعال می‌شود.
- برای CLI نمونه: `python -m tools.excel_io export --out students.xlsx --sheet Students --encoding utf-8-sig` (پس از نصب extra `excel`).
- `write_xlsx` مقادیر عددی و تاریخی را بدون رشته‌سازی مجدد نگه می‌دارد، متادیتای ایجاد/ویرایش را ثابت می‌کند و با پارامتر `memory_limit_bytes` از رشد بیش از حد حافظه جلوگیری می‌کند.
- فایل‌های طلایی بایت‌به‌بایت در مسیر `tests/golden/excel/` نگهداری می‌شوند تا پایداری خروجی تضمین شود و مقادیر خطرناک با `'` خنثی شوند.

## زیرساخت اشتراکی برای Rate Limit و ایدمپوتنسی

### ترتیب میان‌افزارها

- ترتیب اعمال لایه‌ها به صورت `CorrelationID → ContentType → BodySize → Authentication → Idempotency → RateLimit → Router → Observability` است؛
  این چینش تضمین می‌کند شناسهٔ همبستگی قبل از هر پردازش ایجاد شود، نگهبان‌های محتوا/حجم بدنه خطاهای ۴۲۲ بازگردانند،
  ایدمپوتنسی پیش از مصرف توکن‌های نرخ قرار گیرد و Observability آخرین وضعیت را ثبت کند.
- نگهبان‌های Content-Type و Body-Size به‌جای پرتاب استثناء، پاسخ JSON با کد ۴۲۲ و جزئیات دقیق (loc/type) بازمی‌گردانند.

### کلیدها و مقداردهی محدودیت نرخ

- برای هر مسیر و مصرف‌کننده، کلید به شکل `rl:{path}:{consumer}` ساخته می‌شود و سطل توکن در برخورد اول با ظرفیت کامل مقداردهی می‌شود.
- پاسخ 429 شامل هدرهای `Retry-After` و `X-RateLimit-Remaining` است و در بازپخش ایدمپوتنسی، توکن جدیدی مصرف نمی‌شود.

- ماژول‌های `rate_limit_backends.py` و `idempotency_store.py` به‌صورت پیش‌فرض از حافظهٔ محلی استفاده می‌کنند.
- در صورت تعریف `REDIS_URL`، هر دو ماژول به Redis سوئیچ کرده و از namespacing `alloc:` استفاده می‌کنند؛ تست‌ها با یک نمونهٔ Redis اشتراکی اعتبارسنجی شده‌اند.
- محدودسازی نرخ به‌صورت Token Bucket توزیع‌شده اجرا شده و سربار زمانی ثابت دارد؛ سربار لاگ برای درخواست‌های موفق با نمونه‌برداری قابل کنترل (`ALLOC_API_LOG_SAMPLE_RATE`) است.
- ایدمپوتنسی روی پاسخ کامل (Status + Body + Headers) کش می‌شود و استفادهٔ مجدد بدنهٔ متفاوت منجر به خطای `CONFLICT` می‌شود؛ بازپخش با همان بدنه مستقیماً پاسخ ذخیره‌شده را (به همراه `X-Idempotent-Replay`) برمی‌گرداند بدون اینکه نرخ مصرف شود.

## امنیت متریک‌ها و توکن‌ها

- مسیر `/metrics` تنها با هدر `Authorization: Bearer <METRICS_TOKEN>` و درصورت نیاز با IP مجاز در `ALLOC_API_METRICS_IPS` قابل دسترسی است؛ نبود یا عدم‌انطباق توکن با خطای `401 AUTH_REQUIRED` پاسخ داده می‌شود.
- توکن مدیریتی (`ALLOC_API_ADMIN_TOKEN`) و توکن متریک باید مستقل از کلیدهای API نگهداری شوند؛ می‌توان برای سادگی مقدار مشترک انتخاب کرد ولی توصیه می‌شود توکن متریک جداگانه باشد.
- احراز JWT علاوه بر امضای HS256، ادعاهای `iss` و `aud` را با تنظیمات `ALLOC_API_JWT_ISS` و `ALLOC_API_JWT_AUD` کنترل می‌کند.

## راه‌اندازی Redis و تست‌ها

در CI برای تست اشتراک‌گذاری حالت، سرویس Redis باید فعال باشد. نمونهٔ Docker Compose:

```bash
docker run -d --name alloc-redis -p 6379:6379 redis:7-alpine
export REDIS_URL=redis://localhost:6379/5
```

## CLI مدیریت کلید (`tools/api_keys.py`)

- `create`: ساخت کلید جدید با گزینه‌های `--scope` و `--hint`.
- `list`: نمایش وضعیت کلیدها به‌همراه `last_used_at`، `disabled_at` و `rotation_hint`.
- `revoke`: غیرفعالسازی نرم و ثبت زمان `disabled_at`.
- `rotate`: تولید مقدار جدید و چرخش امن کلید موجود؛ مقدار جدید روی STDOUT چاپ می‌شود.

## راهنمای اجرا و پایش

- متغیر `ALLOC_API_LATENCY_BUDGET_MS` آستانهٔ نظارت p95 را مشخص می‌کند؛ متریک `http_latency_budget_exceeded_total` در صورت عبور از بودجه افزایش می‌یابد و لاگ با سطح WARNING ثبت می‌شود.
- نمونهٔ اجرای محلی با Redis:

```bash
export REDIS_URL=redis://localhost:6379/2
export ALLOC_API_METRICS_TOKEN=metrics-secret
export ALLOC_API_ADMIN_TOKEN=ops-secret
uvicorn src.api.api:create_app --factory
```

- برای آزمایش سرریز نرخ:

```bash
curl -s -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json; charset=utf-8' \
  -d @payload.json http://localhost:8000/allocations
```

## محدودسازی نرخ

- الگوریتم سطل توکن با ظرفیت و نرخ تنظیم‌شده برای هر مسیر و هر مصرف‌کننده (شناسهٔ مصرف‌کننده از API key یا `sub` توکن استخراج می‌شود).
- در صورت عبور از حد مجاز، پاسخ `429` با هدرهای `Retry-After` و `X-RateLimit-Remaining` ارسال می‌شود.
- کلیدهای محدودسازی با الگوی `rl:{path}:{consumer}` ساخته می‌شوند تا در تمام نمونه‌ها یکسان باشند و پس از اولین ضربه با ظرفیت کامل مقداردهی اولیه می‌شوند.
- ترتیب میان‌افزارها به‌صورت `CorrelationID → ContentType → BodySize → Authentication → RateLimit → Router → Observability` نگهداری می‌شود تا ثبت لاگ و متریک وضعیت دقیق هر خطای ۴۲۲/۴۲۹ تضمین شود.

## سیاست ایدمپوتنسی

- هدر `Idempotency-Key` باید با الگوی `^[A-Za-z0-9._-]{16,128}$` منطبق باشد.
- نتایج تا ۲۴ ساعت کش می‌شوند؛ درخواست تکراری با بدنهٔ یکسان پاسخ قبلی را با هدر `X-Idempotent-Replay: true` باز می‌گرداند.
- در صورت تغییر بدنه با کلید تکراری، خطای `409 CONFLICT` بازگردانده می‌شود.

## بهینه‌سازی عملکرد و ابزار تست

- در صورت نصب `uvicorn[standard]` (یا extras `perf`)، کتابخانه‌های `uvloop` و `httptools` به‌صورت خودکار فعال می‌شوند و وضعیت انتخاب‌شده در `app.state.runtime_extras` قابل مشاهده است.
- نصب اختیاری `orjson` باعث استفاده از سریال‌ساز سریع‌تر برای لاگ‌های JSON می‌شود؛ در غیر این صورت از `json` استاندارد استفاده می‌کنیم.
- فیکسچر `tests/fixtures/httpx_clients.py` ترنسپورت ASGI را کش می‌کند تا تست‌های HTTPX بدون هزینهٔ ساخت مجدد اجرا شوند.
- آزمون `tests/performance/test_latency_budget.py` دو سناریو (حافظه‌ای و Redis) را برای بودجهٔ تأخیر `ALLOC_API_LATENCY_BUDGET_MS` بررسی می‌کند و در صورت عبور، متریک `http_latency_budget_exceeded_total` افزایش می‌یابد.

## دروازه‌های CI و آنالیز

- Workflow «API Hardening» روی GitHub Actions دستور زیر را اجرا می‌کند تا پوشش فاز پنجم تضمین شود:

  ```bash
  pytest -q -k "excel or admin or metrics_auth or shared_backend or latency_budget or hardened_api"
  ```

- اجرای کامل `pytest -q` تنها در jobهای زمان‌بندی‌شده انجام می‌شود تا CI Pull Requestها سریع باقی بماند.
- آنالیزهای استاتیک شامل `ruff check .` و `mypy --config-file mypy.ini` است؛ پیکربندی جدید تنها پوشه‌های فاز پنج را هدف قرار می‌دهد تا تداخل با ماژول‌های قدیمی رخ ندهد.

## امنیت و احراز هویت

- توکن‌های ایستا و JWT ها باید ASCII و دارای طول ۱۶ تا ۱۲۸ باشند.
- JWT باید با HS256 و کلید مشترک امضاء شده و فیلدهای `exp` و `iat` با خطای زمانی ۱۲۰ ثانیه بررسی می‌شوند.
- کلیدهای API در جدول `api_keys` ذخیره شده‌اند: مقدار هش‌شدهٔ `sha256(salt + key)` با پیشوند ۱۶ کاراکتری و ایندکس فعال.
- CLI مدیریتی در `tools/api_keys.py` برای ایجاد، لیست و ابطال کلیدها در دسترس است.

## ثبت لاگ و متریک‌ها

- همهٔ لاگ‌ها در قالب JSONL با فیلدهای `ts`, `level`, `msg`, `correlation_id`, `request_id`, `consumer_id`, `path`, `method`, `status`, `latency_ms`, `outcome`, `error_code` تولید می‌شوند. شناسهٔ ملی و تلفن هیچ‌گاه به‌صورت خام ثبت نمی‌شوند (هش SHA-256 یا ماسک `09*******12`).
- متریک‌های Prometheus: `http_requests_total`, `http_request_duration_seconds`, `http_requests_in_flight`, `auth_fail_total`, `rate_limit_reject_total`, `alloc_attempt_total`.
- مسیر `/metrics` فقط برای IPهای در لیست سفید یا با هدر `Authorization: Bearer <metrics-token>` قابل دسترس است.

## سناریوهای تست پوشش‌داده‌شده

- ورودی‌های تهی (`null`، `""`، `0`، `'0'`) و ارقام فارسی/عربی.
- کاراکترهای صفر‌عرض در شناسه‌ها (منجر به خطای 422).
- محتوای بیش از ۳۲ کیلوبایت یا `Content-Type` نادرست (422).
- احراز هویت ناقص یا منقضی‌شده (401) و نقش ناکافی (403).
- تجاوز از نرخ درخواست (429).
- درخواست تکراری با کلید ایدمپوتنسی ثابت (بازگشت پاسخ کش‌شده).
- بررسی لاگ و متریک برای اطمینان از حضور `correlation_id` و عدم وجود PII.

## ابزارهای مدیریتی

- اجرای مهاجرت: `alembic upgrade head`
- ساخت کلید جدید: `python -m tools.api_keys create <name>`
- فهرست/ابطال کلید: `python -m tools.api_keys list`، `python -m tools.api_keys revoke <prefix>`

## نکات عملیاتی

- در صورت نیاز به بازتنظیم محدودیت حجم بدنه یا نرخ، متغیرهای محیطی `ALLOC_API_MAX_BODY` و `ALLOC_API_RATE_PER_MIN` استفاده شوند.
- نمک PII (`ALLOC_API_PII_SALT`) را در محیط تولید مقداردهی کنید تا هش‌ها قابل ردیابی نباشند.
- برای افزودن scope جدید، نگاشت `ALLOC_API_REQUIRED_SCOPES` به شکل `"/path=scope1 scope2;..."` در محیط تنظیم شود.
