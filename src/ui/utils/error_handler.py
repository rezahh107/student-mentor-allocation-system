from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import QMessageBox, QWidget

from src.api.exceptions import (
    APIException,
    BusinessRuleException,
    NetworkException,
    ValidationException,
)


class ErrorHandler:
    """مدیریت مرکزی خطاها در برنامه."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self.parent = parent
        self._error_dialog: Optional[QMessageBox] = None

    def handle_error(self, error: Exception, context: str = "") -> None:
        """نمایش مناسب خطا بر اساس نوع آن و ثبت در لاگ."""
        if isinstance(error, NetworkException):
            self._show_network_error(error, context)
        elif isinstance(error, ValidationException):
            self._show_validation_error(error, context)
        elif isinstance(error, BusinessRuleException):
            self._show_business_error(error, context)
        elif isinstance(error, APIException):
            self._show_generic_error(error, context)
        else:
            self._show_generic_error(error, context)

        logging.error(f"Error in {context}: {error}", exc_info=True)

    def _show_network_error(self, error: NetworkException, context: str) -> None:
        QMessageBox.critical(
            self.parent,
            "خطای شبکه",
            f"خطا در ارتباط با سرور:\n{str(error)}\n\nلطفاً اتصال اینترنت را بررسی کنید.",
            QMessageBox.Ok,
        )

    def _show_validation_error(self, error: ValidationException, context: str) -> None:
        QMessageBox.warning(
            self.parent,
            "خطای اعتبارسنجی",
            f"درخواست نامعتبر است:\n{str(error)}",
            QMessageBox.Ok,
        )

    def _show_business_error(self, error: BusinessRuleException, context: str) -> None:
        QMessageBox.information(
            self.parent,
            "قوانین کسب‌وکار",
            f"عملیات مجاز نیست:\n{str(error)}",
            QMessageBox.Ok,
        )

    def _show_generic_error(self, error: Exception, context: str) -> None:
        QMessageBox.critical(
            self.parent,
            "خطای غیرمنتظره",
            f"یک خطای غیرمنتظره رخ داد:\n{type(error).__name__}: {str(error)}",
            QMessageBox.Ok,
        )

