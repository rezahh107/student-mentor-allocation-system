from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """مدیریت ساده تنظیمات برنامه با ذخیره‌سازی JSON."""

    def __init__(self, config_path: str | Path = "config/settings.json") -> None:
        self.config_path = Path(config_path)
        self._defaults: Dict[str, Any] = {
            "dashboard_refresh_interval": 5000,
            "max_students_per_mentor": 20,
            "auto_save": True,
            "same_center_only": True,
            "prefer_lower_load": True,
        }
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return dict(self._defaults)
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            data = {}
        return {**self._defaults, **data}

    def get(self, key: str, default: Any | None = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
        self.save()

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(self._config, handle, indent=2, ensure_ascii=False)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._config)


__all__ = ["ConfigManager"]

