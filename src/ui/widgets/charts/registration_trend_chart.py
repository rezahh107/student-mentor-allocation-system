from __future__ import annotations

from typing import Dict, List

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from src.ui.widgets.charts.chart_themes import ChartThemes


class RegistrationTrendChart(FigureCanvas):
    """نمودار خطی روند ثبت‌نام ۱۲ ماه گذشته."""

    def __init__(self) -> None:
        self.figure: Figure = Figure(figsize=(6, 3), facecolor="white")
        super().__init__(self.figure)
        self._theme = "default"
        self._last_data: List[Dict[str, object]] | None = None
        self._setup_chart()

    def _setup_chart(self) -> None:
        plt.rcParams["font.family"] = ["Vazir", "B Nazanin", "Tahoma"]
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("روند ثبت‌نام 12 ماه گذشته", fontsize=12)
        self.ax.set_xlabel("ماه")
        self.ax.set_ylabel("تعداد ثبت‌نام")
        self.ax.grid(True, alpha=0.3)
        self.figure.tight_layout()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update_data(self._last_data or [])

    def update_data(self, monthly_data: List[Dict[str, object]]) -> None:
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        palette = ChartThemes.apply_theme(self.figure, self._theme)
        if not monthly_data:
            self.ax.text(0.5, 0.5, "داده‌ای موجود نیست", transform=self.ax.transAxes, ha="center", va="center")
            self.draw()
            return
        months = [str(d.get("month", "")) for d in monthly_data]
        counts = [int(d.get("count", 0)) for d in monthly_data]
        color = palette[0] if palette else "#2196F3"
        self.ax.plot(months, counts, "o-", linewidth=2, markersize=6, color=color)
        self.ax.fill_between(range(len(months)), counts, alpha=0.2, color=color)
        self.ax.set_ylim(bottom=0)
        plt.setp(self.ax.get_xticklabels(), rotation=45, ha="right")
        self.figure.tight_layout()
        self.draw()
        self._last_data = list(monthly_data)
