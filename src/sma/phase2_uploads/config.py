from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_ALLOWED_PROFILES = ("ROSTER_V1",)
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 0.05
DEFAULT_RETRY_MAX_DELAY = 0.6
DEFAULT_UI_PREVIEW_ROWS = 5
DEFAULT_NAMESPACE = "default"


@dataclass(frozen=True, slots=True)
class UploadsConfig:
    base_dir: Path
    storage_dir: Path
    manifest_dir: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    allowed_profiles: tuple[str, ...] = DEFAULT_ALLOWED_PROFILES
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY
    ui_preview_rows: int = DEFAULT_UI_PREVIEW_ROWS
    namespace: str = DEFAULT_NAMESPACE

    @staticmethod
    def _assert_keys(data: dict[str, Any], allowed: Iterable[str]) -> None:
        diff = set(data).difference(allowed)
        if diff:
            keys = ", ".join(sorted(diff))
            message = f"Unknown config keys: {keys}"
            raise ValueError(message)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UploadsConfig:
        allowed = {
            "base_dir",
            "storage_dir",
            "manifest_dir",
            "max_upload_bytes",
            "allowed_profiles",
            "retry_attempts",
            "retry_base_delay",
            "retry_max_delay",
            "ui_preview_rows",
            "namespace",
        }
        cls._assert_keys(data, allowed)
        base_dir = Path(data.get("base_dir", Path.cwd())).resolve()
        storage_dir = Path(data.get("storage_dir", base_dir / "uploads"))
        manifest_dir = Path(data.get("manifest_dir", base_dir / "manifests"))
        return cls(
            base_dir=base_dir,
            storage_dir=storage_dir,
            manifest_dir=manifest_dir,
            max_upload_bytes=int(
                data.get("max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)
            ),
            allowed_profiles=tuple(
                data.get("allowed_profiles", DEFAULT_ALLOWED_PROFILES)
            ),
            retry_attempts=int(data.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS)),
            retry_base_delay=float(
                data.get("retry_base_delay", DEFAULT_RETRY_BASE_DELAY)
            ),
            retry_max_delay=float(data.get("retry_max_delay", DEFAULT_RETRY_MAX_DELAY)),
            ui_preview_rows=int(data.get("ui_preview_rows", DEFAULT_UI_PREVIEW_ROWS)),
            namespace=str(data.get("namespace", DEFAULT_NAMESPACE)),
        )

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = UploadsConfig(
    base_dir=Path("./tmp/uploads").resolve(),
    storage_dir=Path("./tmp/uploads/storage").resolve(),
    manifest_dir=Path("./tmp/uploads/manifests").resolve(),
)


__all__ = ["UploadsConfig", "DEFAULT_CONFIG"]
