from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable


DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_ALLOWED_PROFILES = ("ROSTER_V1",)
DEFAULT_IDEMPOTENCY_TTL = 60 * 60 * 24
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
    metrics_token: str
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    allowed_profiles: tuple[str, ...] = DEFAULT_ALLOWED_PROFILES
    idempotency_ttl_seconds: int = DEFAULT_IDEMPOTENCY_TTL
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY
    ui_preview_rows: int = DEFAULT_UI_PREVIEW_ROWS
    namespace: str = DEFAULT_NAMESPACE

    @staticmethod
    def _assert_keys(data: Dict[str, Any], allowed: Iterable[str]) -> None:
        diff = set(data).difference(allowed)
        if diff:
            keys = ", ".join(sorted(diff))
            raise ValueError(f"Unknown config keys: {keys}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UploadsConfig":
        allowed = {
            "base_dir",
            "storage_dir",
            "manifest_dir",
            "metrics_token",
            "max_upload_bytes",
            "allowed_profiles",
            "idempotency_ttl_seconds",
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
        metrics_token = data["metrics_token"]
        return cls(
            base_dir=base_dir,
            storage_dir=storage_dir,
            manifest_dir=manifest_dir,
            metrics_token=metrics_token,
            max_upload_bytes=int(data.get("max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES)),
            allowed_profiles=tuple(data.get("allowed_profiles", DEFAULT_ALLOWED_PROFILES)),
            idempotency_ttl_seconds=int(
                data.get("idempotency_ttl_seconds", DEFAULT_IDEMPOTENCY_TTL)
            ),
            retry_attempts=int(data.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS)),
            retry_base_delay=float(data.get("retry_base_delay", DEFAULT_RETRY_BASE_DELAY)),
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
    metrics_token="local-token",
)
DEFAULT_CONFIG.ensure_directories()
