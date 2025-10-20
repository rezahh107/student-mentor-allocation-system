from __future__ import annotations

from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from sma.ui.widgets.charts.chart_themes import ChartThemes


class AgeDistributionChart(FigureCanvas):
    """هیستوگرام توزیع سنی دانش‌آموزان."""

    def __init__(self) -> None:
        self.figure: Figure = Figure(figsize=(6, 3), facecolor="white")
        super().__init__(self.figure)
        self._theme = "default"
        self._last_data = None
        self._setup_chart()

    def _setup_chart(self) -> None:
        plt.rcParams["font.family"] = ["Vazir", "B Nazanin", "Tahoma"]
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title("توزیع سنی", fontsize=12)
        self.ax.set_xlabel("سن")
        self.ax.set_ylabel("تعداد")
        self.ax.grid(True, alpha=0.3, axis="y")
        self.figure.tight_layout()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.update_data(self._last_data or [])

    def update_data(self, ages: List[int] | Dict[str, int]) -> None:
        self.ax.clear()
        self.ax.set_xlabel("سن")
        self.ax.set_ylabel("تعداد")
        self.ax.grid(True, alpha=0.3, axis="y")
        palette = ChartThemes.apply_theme(self.figure, self._theme)
        if not ages:
            self.ax.text(0.5, 0.5, "داده‌ای موجود نیست", transform=self.ax.transAxes, ha="center", va="center")
            self.draw()
            return
        if isinstance(ages, dict):
            keys = list(ages.keys())
            vals = [ages[k] for k in keys]
            color = palette[2] if len(palette) > 2 else "#4CAF50"
            bars = self.ax.bar(keys, vals, color=color)
            for bar, count in zip(bars, vals):
                if count > 0:
                    self.ax.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(), f"{count}", ha="center", va="bottom")
        else:
            bins = [16, 19, 22, 25, 28, 35]
            color = palette[2] if len(palette) > 2 else "#4CAF50"
            self.ax.hist(ages, bins=bins, color=color, alpha=0.8, edgecolor="white")
        self.figure.tight_layout()
        self.draw()
        self._last_data = ages
