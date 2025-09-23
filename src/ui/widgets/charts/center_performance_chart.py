from __future__ import annotations

from typing import Dict

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from src.ui.widgets.charts.chart_themes import ChartThemes


class CenterPerformanceChart(FigureCanvas):
    """نمودار میله‌ای افقی برای عملکرد مراکز."""

    def __init__(self) -> None:
        self.figure: Figure = Figure(figsize=(6, 3), facecolor="white")
        super().__init__(self.figure)
        self._theme = "default"
        self._last_data: Dict[int, int] | None = None
        self._setup_chart()

    def _setup_chart(self) -> None:
        plt.rcParams["font.family"] = ["Vazir", "B Nazanin", "Tahoma"]
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("عملکرد مراکز", fontsize=12)
        self.ax.set_xlabel("تعداد دانش‌آموز")
        self.figure.tight_layout()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update_data(self._last_data or {})

    def update_data(self, center_data: Dict[int, int]) -> None:
        self.ax.clear()
        self.ax.set_xlabel("تعداد دانش‌آموز")
        palette = ChartThemes.apply_theme(self.figure, self._theme)
        if not center_data:
            self.ax.text(0.5, 0.5, "داده‌ای موجود نیست", transform=self.ax.transAxes, ha="center", va="center")
            self.draw()
            return
        center_names = {1: "مرکز", 2: "گلستان", 3: "صدرا"}
        centers = [center_names.get(k, str(k)) for k in center_data.keys()]
        values = list(center_data.values())
        y_pos = range(len(centers))
        colors = palette[: len(values)] if palette else ["#FF6B6B", "#4ECDC4", "#45B7D1"][: len(values)]
        self.ax.barh(list(y_pos), values, color=colors)
        self.ax.set_yticks(list(y_pos))
        self.ax.set_yticklabels(centers)
        for i, val in enumerate(values):
            self.ax.text(val, i, f" {val:,}", va="center", ha="left")
        self.ax.grid(True, alpha=0.3, axis="x")
        if values:
            self.ax.set_xlim(0, max(values) * 1.2)
        self.figure.tight_layout()
        self.draw()
        self._last_data = dict(center_data)
