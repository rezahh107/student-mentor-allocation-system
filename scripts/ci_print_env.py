#!/usr/bin/env python3
"""Emit a deterministic, sanitized environment snapshot for CI debugging."""
from __future__ import annotations

import json
import os
import platform
import sys
from importlib import import_module
from typing import Dict

SENSITIVE_KEYWORDS = {"TOKEN", "SECRET", "PASSWORD", "KEY", "AWS", "PRIVATE"}


def sanitize_env() -> Dict[str, str]:
    sanitized = {}
    for key in sorted(os.environ):
        value = os.environ.get(key, "")
        if any(word in key for word in SENSITIVE_KEYWORDS):
            sanitized[key] = "***masked***"
        else:
            sanitized[key] = value
    return sanitized


def gather_versions() -> Dict[str, str]:
    packages = ["fastapi", "pytest", "redis", "pydantic", "uvicorn"]
    versions: Dict[str, str] = {}
    for name in packages:
        try:
            module = import_module(name)
        except ImportError:
            versions[name] = "not-installed"
        else:
            version = getattr(module, "__version__", "unknown")
            versions[name] = str(version)
    return versions


def main() -> None:
    snapshot = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ci": os.getenv("GITHUB_ACTIONS", "local"),
        "timezone": os.getenv("TIMEZONE", os.getenv("TZ", "unknown")),
        "ci_run_id": os.getenv("CI_RUN_ID", "local"),
        "packages": gather_versions(),
        "env": sanitize_env(),
    }
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
