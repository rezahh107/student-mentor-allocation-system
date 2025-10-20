# کنترل زمان و تزریق Clock

این مخزن برای تمام مسیرهای زمان‌محور از یک Clock تزریق‌شده با منطقهٔ زمانی **Asia/Tehran** استفاده می‌کند. ماژول `src/core/clock.py` رابط‌های اصلی را فراهم می‌کند:

- `SystemClock`: خواندن زمان واقعی (TZ = Asia/Tehran)
- `FrozenClock`: برای تست‌های کاملاً قطعی
- `ensure_clock(...)`: نرمال‌سازی وابستگی‌ها (Clock، callable یا `None`)

## تزریق در FastAPI

کلاس‌های وب از شیم `src/web/deps/clock.py` برای دریافت Clock مشترک استفاده می‌کنند:

```python
from fastapi import Depends
from sma.web.deps.clock import injected_clock

@app.get("/now")
def read_time(clock: Clock = Depends(injected_clock)):
    return {"ts": clock.now().isoformat()}
```

در تست‌ها می‌توانید Clock را موقتاً فریز کنید:

```python
from sma.core.clock import FrozenClock
from sma.web.deps.clock import override_clock

with override_clock(FrozenClock(timezone=Clock.for_tehran().timezone)) as clock:
    clock.set(datetime(2023, 3, 21, tzinfo=ZoneInfo("Asia/Tehran")))
    ...
```

## تضمین قطعی بودن

- گارد `tools/guards/wallclock_repo_guard.py` هر استفادهٔ مستقیم از `datetime.now`، `time.time`، `date.today` و `pandas.Timestamp.now` را در کد زمان اجرای پروژه مسدود می‌کند.
- تنها استثناء برای استفاده از ساعت سیستم، پوشهٔ `scripts/`، `migrations/` و ماژول‌هایی است که با نظر مشخص (`# WALLCLOCK_ALLOW`) علامت‌گذاری شده‌اند.
- استفاده از `Asia/Baku` خارج از `tools/guards/*` و نمونه‌های مستندات (`docs/`) ممنوع است؛ خط لولهٔ CI این موضوع را بررسی می‌کند.
- تست‌های `tests/time/` و `tests/mw/` رفتار ساعت و زنجیرهٔ RateLimit → Idempotency → Auth را پوشش می‌دهند.
- برای سیستم‌هایی که پایگاه دادهٔ IANA ندارند (مثلاً Windows)، بستهٔ `tzdata` را نصب کنید تا `ZoneInfo("Asia/Tehran")` قابل resolves باشد.
