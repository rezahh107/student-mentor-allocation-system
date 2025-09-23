from __future__ import annotations

from typing import Dict, List


class ChartThemes:
    THEMES: Dict[str, Dict] = {
        "default": {
            "colors": ["#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6"],
            "background": "#ffffff",
            "text_color": "#2c3e50",
            "grid_alpha": 0.3,
        },
        "dark": {
            "colors": ["#5dade2", "#ec7063", "#58d68d", "#f7dc6f", "#bb8fce"],
            "background": "#2c3e50",
            "text_color": "#ecf0f1",
            "grid_alpha": 0.2,
        },
        "colorful": {
            "colors": ["#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7"],
            "background": "#ffffff",
            "text_color": "#2d3436",
            "grid_alpha": 0.4,
        },
    }

    @classmethod
    def apply_theme(cls, fig, theme_name: str = "default") -> List[str]:
        """اعمال تم روی شکل matplotlib و بازگرداندن پالت رنگ."""
        theme = cls.THEMES.get(theme_name, cls.THEMES["default"])
        fig.patch.set_facecolor(theme["background"])
        for ax in fig.get_axes():
            ax.set_facecolor(theme["background"])
            ax.tick_params(colors=theme["text_color"])  # type: ignore[arg-type]
            ax.xaxis.label.set_color(theme["text_color"])  # type: ignore[attr-defined]
            ax.yaxis.label.set_color(theme["text_color"])  # type: ignore[attr-defined]
            ax.title.set_color(theme["text_color"])  # type: ignore[attr-defined]
            ax.grid(True, alpha=theme["grid_alpha"])  # type: ignore[arg-type]
        return list(theme["colors"])  # copy

