# نصب و راه‌اندازی

این راهنما نصب وابستگی‌ها و اجرای برنامه را توضیح می‌دهد.

## پیش‌نیازها
- Python 3.8+
- pip / venv
- سیستم‌عامل Windows/Linux/macOS

## نصب وابستگی‌ها
```
python -m venv .venv
source .venv/bin/activate  # ویندوز: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt -c constraints-win.txt
```

> توجه: استفاده از فایل `constraints-win.txt` برای نصب وابستگی‌ها در ویندوز اجباری و برای سایر سیستم‌ها نیز به‌منظور بازتولیدپذیری توصیه می‌شود.

## فونت‌های فارسی
- فونت‌ها را در مسیر `assets/fonts/` قرار دهید:
  - `Vazir.ttf` یا `Vazir-Regular.ttf`
  - `B-Nazanin.ttf`
  - `Tahoma.ttf` (اختیاری)
- نبود فونت‌ها مانع اجرای برنامه نیست؛ ظاهر و PDF با فونت پیش‌فرض رندر می‌شوند.

## اجرای برنامه
```
python -m src.ui.main
```

## نکات
- در صورت استفاده از Realtime (اختیاری)، سرویس WebSocket را در `ws://localhost:8000/ws` راه‌اندازی کنید یا URL را در کد Presenter تغییر دهید.
- در حالت توسعه، از Mock Backend استفاده می‌شود؛ با تغییر `APIClient(use_mock=False)` به API واقعی متصل شوید.

