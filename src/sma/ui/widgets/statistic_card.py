from __future__ import annotations

from PyQt5.QtCore import QPropertyAnimation, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)


class StatisticCard(QFrame):
    """کارت آماری داشبورد با استایل فارسی."""

    def __init__(self, title: str, icon: str, color: str, initial_value: str = "0", subtitle: str = "") -> None:
        super().__init__()
        self.title = title
        self.icon = icon
        self.color = color
        self._setup_ui(initial_value, subtitle)

    def _setup_ui(self, initial_value: str, subtitle: str) -> None:
        self.setFrameStyle(QFrame.Box)
        self.setFixedHeight(140)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        icon_lbl = QLabel(self.icon)
        icon_lbl.setStyleSheet(
            f"""
            font-size: 28px; color: {self.color}; background-color: {self.color}20;
            border-radius: 20px; padding: 8px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
            """
        )
        icon_lbl.setAlignment(Qt.AlignCenter)
        title_lbl = QLabel(self.title)
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #495057;")
        header.addWidget(icon_lbl)
        header.addWidget(title_lbl)
        header.addStretch()

        self.value_label = QLabel(initial_value)
        self.value_label.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {self.color}; margin: 5px 0;")

        self.change_label = QLabel("")
        self.change_label.setStyleSheet("font-size: 12px; padding: 2px 6px; border-radius: 10px;")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet("font-size: 12px; color: #6c757d;")

        ch_lay = QHBoxLayout()
        ch_lay.addWidget(self.change_label)
        ch_lay.addWidget(self.subtitle_label)
        ch_lay.addStretch()

        layout.addLayout(header)
        layout.addWidget(self.value_label)
        layout.addLayout(ch_lay)
        layout.addStretch()

        self.setStyleSheet(
            f"""
            StatisticCard {{
                background-color: white; border: 1px solid #e9ecef; border-radius: 12px; border-left: 4px solid {self.color};
            }}
            """
        )

    def update_value(self, value: str, change: str | None = None, percentage: str | None = None, trend: str | None = None) -> None:
        self._animate_value(value)
        if change:
            self._update_change(change, trend)
        elif percentage:
            self.change_label.setText(percentage)
            self.change_label.setStyleSheet(
                "font-size: 12px; color: #495057; background-color: #f8f9fa; padding: 2px 6px; border-radius: 10px;"
            )

    def _animate_value(self, new_value: str) -> None:
        eff = QGraphicsOpacityEffect()
        self.value_label.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.3)
        anim.finished.connect(lambda: self._complete_update(new_value))
        anim.start()
        self._anim = anim  # keep ref

    def _complete_update(self, new_value: str) -> None:
        self.value_label.setText(new_value)
        eff = self.value_label.graphicsEffect()
        anim = QPropertyAnimation(eff, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(0.3)
        anim.setEndValue(1.0)
        anim.start()
        self._anim2 = anim

    def _update_change(self, change: str, trend: str | None = None) -> None:
        if trend == "up" or (change.startswith("+") and not change.startswith("+0")):
            color = "#28a745"; icon = "↗️"
        elif trend == "down" or change.startswith("-"):
            color = "#dc3545"; icon = "↘️"
        else:
            color = "#6c757d"; icon = "→"
        self.change_label.setText(f"{icon} {change}")
        self.change_label.setStyleSheet(
            f"font-size: 12px; color: white; background-color: {color}; padding: 2px 6px; border-radius: 10px; font-weight: bold;"
        )

