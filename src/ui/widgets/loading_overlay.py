from __future__ import annotations

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QMovie
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingOverlay(QWidget):
    """اورلی نیمه‌شفاف با انیمیشن بارگذاری.

    نحوه استفاده:
        overlay = LoadingOverlay(parent_widget)
        overlay.show_with_message("در حال بارگذاری...")
        # ... عملیات async
        overlay.hide()
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("LoadingOverlay")
        self._setup_ui()
        self.hide()

    def _setup_ui(self) -> None:
        """ایجاد عناصر ظاهری بارگذاری."""
        self.setStyleSheet(
            """
            #LoadingOverlay { background-color: rgba(0, 0, 0, 140); }
            LoadingOverlay { background-color: rgba(0, 0, 0, 140); }
            """
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self.spinner = QLabel(self)
        self.spinner.setAlignment(Qt.AlignCenter)
        self.movie = QMovie("assets/spinner.gif")
        if self.movie.isValid():
            self.movie.setScaledSize(QSize(64, 64))
            self.spinner.setMovie(self.movie)
        else:
            self.spinner.setText("⏳")
            self.spinner.setStyleSheet("color: white; font-size: 48px;")

        self.message = QLabel("در حال بارگذاری...", self)
        self.message.setStyleSheet(
            "color: white; font-size: 14px; font-family: 'Vazir'; margin-top: 10px;"
        )
        self.message.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.spinner)
        layout.addWidget(self.message)

    def show_with_message(self, message: str) -> None:
        """نمایش اورلی با پیام دلخواه."""
        self.message.setText(message)
        self.resize(self.parent().size())
        if self.movie and self.movie.isValid():
            self.movie.start()
        self.show()
        self.raise_()

