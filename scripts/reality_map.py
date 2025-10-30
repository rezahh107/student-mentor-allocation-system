#!/usr/bin/env python3
"""Reality Map – Verify AGENTS.md v5.2 compliance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from importlib import import_module
from inspect import getmembers
from pathlib import Path

from fastapi import FastAPI

errors: list[str] = []

_DEFAULT_ENV = {
    "IMPORT_TO_SABT_REDIS__DSN": "redis://localhost:6379/0",
    "IMPORT_TO_SABT_REDIS__NAMESPACE": "import_to_sabt_reality_map",
    "IMPORT_TO_SABT_DATABASE__DSN": "postgresql://user:pass@localhost:5432/db",
    "IMPORT_TO_SABT_AUTH__SERVICE_TOKEN": "reality-map-service-token",
    "IMPORT_TO_SABT_AUTH__METRICS_TOKEN": "reality-map-metrics-token",
    "IMPORT_TO_SABT_AUTH__TOKENS_ENV_VAR": "TOKENS",
    "IMPORT_TO_SABT_AUTH__DOWNLOAD_SIGNING_KEYS_ENV_VAR": "DOWNLOAD_SIGNING_KEYS",
    "IMPORT_TO_SABT_AUTH__DOWNLOAD_URL_TTL_SECONDS": "900",
}


def _ensure_root_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    for candidate in (src, root):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


def _ensure_minimal_env() -> None:
    for key, value in _DEFAULT_ENV.items():
        os.environ.setdefault(key, value)


def _load_app() -> FastAPI | None:
    mods: Iterable[str] = ("main", "app.main", "src.main")
    for module_name in mods:
        try:
            module = import_module(module_name)
        except (ImportError, RuntimeError, ValueError):
            continue
        for _, candidate in getmembers(module):
            if isinstance(candidate, FastAPI):
                return candidate
    return None


def check_agents_md() -> None:
    path = Path("AGENTS.md")
    if not path.exists():
        errors.append("AGENTS.md missing")
        return
    content = path.read_text(encoding="utf-8", errors="ignore")
    if "v5.2" not in content:
        errors.append("AGENTS.md version != v5.2")
    else:
        print("✅ AGENTS.md v5.2 confirmed")


def check_python_version() -> None:
    version = sys.version_info
    if (version.major, version.minor, version.micro) != (3, 11, 9):
        rendered = f"Python {version.major}.{version.minor}.{version.micro} != 3.11.9"
        errors.append(rendered)
    else:
        print(f"✅ Python {version.major}.{version.minor}.{version.micro} OK")


def list_endpoints(app: FastAPI | None) -> None:
    if app is None:
        errors.append("FastAPI app not found for endpoint enumeration")
        return
    try:
        paths = sorted(app.openapi()["paths"].keys())
    except (AttributeError, RuntimeError) as exc:
        errors.append(f"Failed to load OpenAPI: {exc}")
        return
    print("✅ Endpoints:", json.dumps(paths, indent=2, ensure_ascii=False))


def check_middleware_order(app: FastAPI | None) -> None:
    if app is None:
        errors.append("FastAPI app not found for middleware inspection")
        return
    chain: list[str] = []
    for middleware in getattr(app, "user_middleware", []):
        middleware_cls = getattr(middleware, "cls", middleware.__class__)
        chain.append(middleware_cls.__name__)
    expected = ["RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware"]
    try:
        positions = [chain.index(name) for name in expected]
    except ValueError:
        errors.append(f"Middleware order missing: {'|'.join(chain)}")
        return
    if positions == sorted(positions):
        print("✅ Middleware order correct")
    else:
        errors.append(f"Middleware order wrong: {'|'.join(chain)}")


def check_external(tool: str, *args: str) -> None:
    try:
        subprocess.run([tool, *args], check=True, capture_output=True, timeout=2)
        print(f"✅ {tool} available")
    except FileNotFoundError:
        print(f"⚠️ {tool} not installed (skipping check)")
    except subprocess.CalledProcessError as exc:
        errors.append(f"{tool} check failed: {exc.stderr.decode('utf-8', 'ignore')}")


def main() -> int:
    _ensure_minimal_env()
    _ensure_root_on_path()
    check_agents_md()
    check_python_version()
    app = _load_app()
    list_endpoints(app)
    check_middleware_order(app)
    check_external("redis-cli", "ping")
    check_external("pg_isready")
    if errors:
        print("❌ Reality Map FAIL")
        for item in errors:
            print("-", item)
        return 1
    print("✅ All checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
