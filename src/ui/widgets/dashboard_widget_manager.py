from __future__ import annotations

from typing import Dict


class DashboardWidgetManager:
    """مدیریت چینش و سفارشی‌سازی ویجت‌های داشبورد."""

    def __init__(self) -> None:
        self.widget_configs: Dict[str, Dict] = {
            "stat_cards": {"visible": True, "order": 1, "size": "medium"},
            "gender_chart": {"visible": True, "order": 2, "size": "small"},
            "trend_chart": {"visible": True, "order": 3, "size": "large"},
            "center_chart": {"visible": True, "order": 4, "size": "medium"},
            "age_chart": {"visible": True, "order": 5, "size": "small"},
            "performance_table": {"visible": True, "order": 6, "size": "large"},
        }

    def save_layout(self, layout_config: Dict) -> None:
        """ذخیره چینش سفارشی (TODO: ذخیره در فایل/دیتابیس)."""
        self.widget_configs.update(layout_config)

    def load_layout(self) -> Dict:
        """بارگذاری چینش ذخیره‌شده (فعلاً پیش‌فرض)."""
        return dict(self.widget_configs)

    def reset_to_default(self) -> None:
        """بازگردانی به حالت پیش‌فرض."""
        self.__init__()

