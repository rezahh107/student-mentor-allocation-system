from __future__ import annotations

import asyncio
import logging
import sys

try:
    from PyQt5.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover - user environment specific
    print(
        "PyQt5 نصب نشده است؛ برای اجرای رابط کاربری دستور 'pip install .[ui]' را اجرا کنید.",
        file=sys.stderr,
    )
    sys.exit(2)
except ImportError as exc:  # pragma: no cover - user environment specific
    print(
        f"بارگذاری PyQt5 با خطا مواجه شد: {exc}; لطفاً وابستگی اختیاری ui را نصب کنید.",
        file=sys.stderr,
    )
    sys.exit(2)

from qasync import run

from sma.api.client import APIClient
from sma.ui.presenters.main_presenter import MainPresenter
from sma.ui.windows.main_window import MainWindow
from sma.ui.core import fonts as fontutil


async def main() -> bool:
    """نقطه ورود اصلی با پشتیبانی async و qasync."""
    app = QApplication.instance() or QApplication(sys.argv)
    # نصب فونت‌های فارسی و پیکربندی matplotlib
    try:
        finfo = fontutil.install_persian_fonts(app)
        fontutil.configure_matplotlib(app.font().family())
    except Exception as error:
        # در صورت بروز خطا، ادامه می‌دهیم و به فونت پیش‌فرض اتکا می‌کنیم
        logging.warning("بارگذاری فونت‌های برنامه با خطا مواجه شد: %s", error)

    # ایجاد و نمایش پنجره اصلی
    api_client = APIClient(use_mock=True)
    presenter = MainPresenter(api_client)
    window = MainWindow(presenter)
    window.show()

    # بازداشتن تابع تا زمان خروج برنامه
    stopper: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

    def _on_quit() -> None:
        if not stopper.done():
            stopper.set_result(True)

    app.aboutToQuit.connect(_on_quit)
    await stopper
    return True


if __name__ == "__main__":
    # اجرای برنامه با حلقه رویداد qasync
    try:
        run(main())
    except asyncio.CancelledError as error:
        logging.info("اجرای برنامه با سیگنال لغو خاتمه یافت: %s", error)
