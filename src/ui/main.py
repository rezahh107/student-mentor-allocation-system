from __future__ import annotations

import asyncio
import logging
import sys

from PyQt5.QtWidgets import QApplication
from qasync import QEventLoop, run

from src.api.client import APIClient
from src.ui.presenters.main_presenter import MainPresenter
from src.ui.windows.main_window import MainWindow
from src.ui.core import fonts as fontutil


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
