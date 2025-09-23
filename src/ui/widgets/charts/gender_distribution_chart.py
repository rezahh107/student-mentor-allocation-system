from __future__ import annotations

from typing import Dict

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from src.ui.widgets.charts.chart_themes import ChartThemes


class GenderDistributionChart(FigureCanvas):
    """نمودار دونات برای توزیع جنسیت."""

    def __init__(self) -> None:
        self.figure: Figure = Figure(figsize=(4, 3), facecolor="white")
        super().__init__(self.figure)
        self._theme = "default"
        self._last_data: Dict[int, int] | None = None
        self._setup_chart()

    def _setup_chart(self) -> None:
        plt.rcParams["font.family"] = ["Vazir", "B Nazanin", "Tahoma"]
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("توزیع جنسیتی", fontsize=12)
        self.ax.pie([1], colors=["#f0f0f0"], startangle=90)
        centre = plt.Circle((0, 0), 0.55, fc="white")
        self.ax.add_artist(centre)
        self.figure.tight_layout()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        # re-render with last data
        self.update_data(self._last_data or {})

    def update_data(self, gender_data: Dict[int, int]) -> None:
        self.ax.clear()
        palette = ChartThemes.apply_theme(self.figure, self._theme)
        labels = []
        sizes = []
        colors = []
        if 0 in gender_data:
            labels.append("زن")
            sizes.append(gender_data[0])
            colors.append(palette[1] if len(palette) > 1 else "#E91E63")
        if 1 in gender_data:
            labels.append("مرد")
            sizes.append(gender_data[1])
            colors.append(palette[0] if len(palette) > 0 else "#2196F3")
        if not sizes:
            self.ax.text(0.5, 0.5, "داده‌ای موجود نیست", transform=self.ax.transAxes, ha="center", va="center")
            self.draw()
            return
        wedges, _texts, _auto = self.ax.pie(
            sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90, pctdistance=0.85, labeldistance=1.1
        )
        centre = plt.Circle((0, 0), 0.55, fc="white")
        self.ax.add_artist(centre)
        total = sum(sizes)
        self.ax.text(0, 0, f"کل\n{total:,}", ha="center", va="center", fontsize=11)
        self.ax.axis("equal")
        self.figure.tight_layout()
        self.draw()
        self._last_data = dict(gender_data)
