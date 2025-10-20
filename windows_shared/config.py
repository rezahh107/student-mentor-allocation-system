"""Shared configuration helpers for Windows launcher/service integrations."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from hashlib import blake2s
from pathlib import Path
from typing import Any, Mapping

from platformdirs import PlatformDirs

from sma.core.clock import Clock, tehran_clock
from sma.phase6_import_to_sabt.sanitization import sanitize_text, secure_digest
from sma.reliability.atomic import atomic_write_json

APP_NAME = "StudentMentorApp"
APP_VENDOR = "ImportToSabt"
CONFIG_ENV = "STUDENT_MENTOR_APP_CONFIG_DIR"
PORT_OVERRIDE_ENV = "STUDENT_MENTOR_APP_PORT"
PORT_SALT_ENV = "STUDENT_MENTOR_APP_PORT_SALT"
MACHINE_ENV = "STUDENT_MENTOR_APP_MACHINE_ID"
CONFIG_FILENAME = "config.json"
LOCK_FILENAME = "launcher.lock"
BASE_PORT = 24700
PORT_SPREAD = 1000
MIN_PORT = 1024
MAX_PORT = 49151


class ConfigError(RuntimeError):
    """Raised when persisted configuration cannot be normalised."""


def _sanitize_component(value: str, fallback: str) -> str:
    text = sanitize_text(value) or fallback
    text = text.replace(" ", "_")
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_"})
    return (safe[:48] or fallback)


SAFE_APP_NAME = _sanitize_component(APP_NAME, "StudentMentorApp")
SAFE_VENDOR = _sanitize_component(APP_VENDOR, "ImportToSabt")


@dataclass(slots=True)
class LauncherConfig:
    port: int
    host: str = "127.0.0.1"
    ui_path: str = "/ui"
    version: int = 1

    def as_mapping(self, *, clock: Clock | None = None) -> Mapping[str, Any]:
        active_clock = clock or tehran_clock()
        return {
            "version": int(self.version),
            "host": sanitize_text(self.host) or "127.0.0.1",
            "port": int(self.port),
            "ui_path": _normalise_ui_path(self.ui_path),
            "updated_at": active_clock.now().isoformat(),
        }


def config_dir() -> Path:
    override = os.getenv(CONFIG_ENV)
    if override:
        sanitized = sanitize_text(override) or override.strip()
        return Path(sanitized).expanduser()
    dirs = PlatformDirs(SAFE_APP_NAME, SAFE_VENDOR)
    return Path(dirs.user_config_dir)


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def lock_path() -> Path:
    return config_dir() / LOCK_FILENAME


def _port_in_range(port: int) -> bool:
    return MIN_PORT <= port <= MAX_PORT


def _normalise_ui_path(path: str) -> str:
    candidate = sanitize_text(path or "/ui") or "/ui"
    if not candidate.startswith("/"):
        candidate = "/" + candidate
    return candidate.replace("//", "/")


def _machine_fingerprint() -> str:
    override = os.getenv(MACHINE_ENV)
    if override:
        return sanitize_text(override) or "machine"
    node = sanitize_text(platform.node())
    return node or "machine"


def _port_seed() -> str:
    machine = _machine_fingerprint()
    salt = sanitize_text(os.getenv(PORT_SALT_ENV, ""))
    return secure_digest(f"{machine}:{salt}") if salt else secure_digest(machine)


def compute_port(base: int = BASE_PORT) -> int:
    override = os.getenv(PORT_OVERRIDE_ENV)
    if override:
        try:
            candidate = int(override)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ConfigError("PORT_OVERRIDE_INVALID") from exc
        if _port_in_range(candidate):
            return candidate
    base = max(MIN_PORT, min(base, MAX_PORT - PORT_SPREAD))
    digest = blake2s(_port_seed().encode("utf-8"), digest_size=4).digest()
    offset = int.from_bytes(digest, "big") % PORT_SPREAD
    computed = base + offset
    if computed > MAX_PORT:
        span = MAX_PORT - MIN_PORT
        computed = MIN_PORT + ((computed - MIN_PORT) % span)
    return max(MIN_PORT, min(computed, MAX_PORT))


def load_launcher_config(*, clock: Clock | None = None) -> LauncherConfig:
    cfg_path = config_path()
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError("CONFIG_JSON_INVALID") from exc
        port = int(raw.get("port", 0))
        host = sanitize_text(raw.get("host", "127.0.0.1")) or "127.0.0.1"
        ui_path = _normalise_ui_path(str(raw.get("ui_path", "/ui")))
        if not _port_in_range(port):
            port = compute_port()
        return LauncherConfig(port=port, host=host, ui_path=ui_path, version=int(raw.get("version", 1)))

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    config = LauncherConfig(port=compute_port())
    persist_launcher_config(config, clock=clock)
    return config


def persist_launcher_config(config: LauncherConfig, *, clock: Clock | None = None) -> None:
    payload = config.as_mapping(clock=clock)
    cfg_path = config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cfg_path, payload)


__all__ = [
    "APP_NAME",
    "CONFIG_FILENAME",
    "ConfigError",
    "LauncherConfig",
    "compute_port",
    "config_dir",
    "config_path",
    "lock_path",
    "load_launcher_config",
    "persist_launcher_config",
]
