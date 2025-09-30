# عملیات سامانه تخصیص دانشجو-مربی

## sso-onboarding

### نمای کلی
- این مرحله، اتصال SSO سازمانی (OIDC/SAML) را فعال می‌کند و نشست‌های گذرگاهی را در Redis مدیریت می‌نماید.
- تمامی زمان‌ها با ساعت تزریق‌شده (Asia/Tehran) محاسبه می‌شوند؛ هیچ استفاده‌ای از `datetime.now()` مجاز نیست.

### پیش‌نیازهای Go/No-Go
- [ ] متغیرهای محیطی مطابق `src/config/env_schema.py::SSOConfig` مقداردهی شده‌اند؛ هیچ کلید ناشناخته‌ای وجود ندارد.
- [ ] آداپتور انتخابی (OIDC یا SAML) در حالت سبز (`SSO_BLUE_GREEN_STATE=green`) گرم و آماده است.
- [ ] تست‌های واحد و یکپارچه `pytest -q tests/auth tests/mw tests/obs tests/blue_green` بدون خطا اجرا شده‌اند.
- [ ] دسترسی `/metrics` همچنان با توکن موجود محافظت می‌شود و شمارنده‌های `auth_ok_total` و `auth_fail_total{reason}` افزایش می‌یابند.
- [ ] لاگ‌ها و رخدادهای ممیزی فاقد PII هستند (شناسه‌ها هش یا ماسک شده‌اند).

### فرآیند فعال‌سازی آبی/سبز
1. مقداردهی `SSO_BLUE_GREEN_STATE=warming` و بارگذاری نرم‌افزار جدید.
2. اجرای تست‌های دود `tests/mw/test_order_auth_callback.py` و `tests/blue_green/test_zero_downtime.py` روی محیط در حال گرم شدن.
3. پس از موفقیت، تغییر مقدار به `green` و نظارت بر متریک‌های `auth_duration_seconds` (p95 < 200ms).
4. در صورت بروز خطا، بازگشت به مقدار `blue`؛ نشست‌های فعال با TTL ۱۵ دقیقه در Redis باقی می‌مانند.

### ماتریس نگاشت ویژگی‌ها
| منبع | نقش | اسکوپ مرکز | توضیح |
|------|-----|------------|-------|
| OIDC.claims.role | ADMIN/MANAGER | `center_scope` یا `ALL` | با نرمال‌سازی ارقام فارسی/عربی |
| SAML.Attribute `role` | ADMIN/MANAGER | `center_scope` | رد کردن مقادیر نامعتبر |
| LDAP گروه | ADMIN/MANAGER | استخراج‌شده از قوانین `LDAP_GROUP_RULES` | قالب `گروه:نقش:اسکوپ` |

### عیب‌یابی سریع
- «کلید ناشناخته» → بررسی متغیرهای محیطی با `tests/config/test_env_schema.py`.
- «توکن بازگشتی نامعتبر است» → بازبینی JWKS و مطابقت `kid` در `auth/oidc_adapter.py`.
- «پیام هویتی بسیار بزرگ است» → تأیید اندازه Assertion (حداکثر ۲۵۰KB).
- زمان‌های طولانی در Callback → بررسی تأخیر LDAP و شمارش تلاش‌های تکرار (`auth_retry_attempts_total`).

## sso-oncall-metrics

- هشدار «ورودهای مکرر ناموفق» زمانی فعال می‌شود که `auth_retry_exhaustion_total{adapter,reason}` در مدت ۵ دقیقه بیش از ۳ مقدار جدید ثبت کند؛ تفکیک بر اساس `adapter ∈ {"oidc","ldap"}` و `reason` (مانند `"jwks"` یا `"timeout"`).
- برای پایش تأخیرها، هیستوگرام `auth_retry_backoff_seconds` را با تمرکز بر باکت‌های >0.2s بررسی کنید؛ افزایش ناگهانی نشان‌دهنده کندی سرویس IdP یا LDAP است.
- هنگام بررسی رخداد، ابتدا `auth_retry_attempts_total` و `auth_retry_exhaustion_total` را از `/metrics` (با توکن موجود) نمونه‌برداری کنید و سپس `DebugContext` ثبت‌شده در لاگ‌های JSON را با فیلد `debug_context` استخراج کنید؛ این فیلد شامل `rid/operation/namespace/last_error` و خلاصه کلیدهای Redis مجاز است.
- اگر مقدار هیستوگرام رشد می‌کند ولی شمارندهٔ `exhaustion` ثابت است، احتمالاً backoff جبران‌گر است؛ جدول «عیب‌یابی سریع» را دنبال کنید و با استفاده از `DebugContext` وضعیت کلیدهای `sso_session:*` را بررسی نمایید.
- در زمان پاسخ‌گویی به هشدار، لاگ‌ها را با فیلتر `rid` بررسی کنید؛ در صورت وجود چند RID با خطا، از اسکریپت‌های موجود در `tests/debug/test_debug_context_default_factory_integration.py` برای بازتولید شرایط استفاده کنید.

### بازیابی و بازگشت
- برای rollback، مقدار `SSO_BLUE_GREEN_STATE` را به `blue` برگردانید؛ این کار POSTها را مسدود می‌کند اما نشست‌های موجود فعال می‌مانند تا TTL خاتمه یابد.
- پاک‌سازی دستی نشست‌ها: اجرای `redis-cli --scan 'sso_session:*' | xargs redis-cli del` در صورت نیاز (با احتیاط).
- تمامی رویدادهای ممیزی در جدول `audit_events` با `action ∈ {AUTHN_OK, AUTHN_FAIL}` موجود است؛ جهت بررسی رخدادهای اخیر از ابزار گزارش‌گیری استفاده کنید.
