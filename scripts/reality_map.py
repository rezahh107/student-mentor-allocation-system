#!/usr/bin/env python3
"""
Reality Map v5.0 - Production-Grade Compliance Validator
Enhanced with flexible discovery and comprehensive error handling
"""
import sys
import json
import subprocess
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum


class CheckStatus(Enum):
    PASS = "✅"
    FAIL = "❌"
    WARN = "⚠️"
    INFO = "ℹ️"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    details: Optional[str] = None


class RealityMapError(Exception):
    pass


class RealityMap:
    def __init__(self):
        self._ensure_root_on_path()
        self.results: List[CheckResult] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.config = self._load_config()

    def _ensure_root_on_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        src = root / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))

    def _load_config(self) -> Dict[str, Any]:
        return {
            "REQUIRED_PYTHON": (3, 11, 9),
            "AGENTS_VERSION": "v5.2",  # accept v5.2 or v5.2-LOCAL
            "REQUIRED_ENDPOINTS": ["/exports", "/health", "/metrics"],
            "MIDDLEWARE_ORDER": ["RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware"],
            "PERFORMANCE_BUDGETS": {
                "export_p95": 15.0,
                "export_p99": 20.0,
                "memory_mb": 150.0,
                "health_p95": 0.2
            }
        }

    def check_agents_md(self) -> CheckResult:
        try:
            p = Path("AGENTS.md")
            if not p.exists():
                return CheckResult("AGENTS.md", CheckStatus.FAIL, "File not found",
                                   "Ensure AGENTS.md is present (v5.2 or v5.2-LOCAL)")
            content = p.read_text(encoding="utf-8", errors="ignore")
            version = self.config["AGENTS_VERSION"]
            if version not in content and (version + "-LOCAL") not in content:
                return CheckResult("AGENTS.md", CheckStatus.FAIL,
                                   f"Version mismatch (expected {version} or {version}-LOCAL)",
                                   "Open AGENTS.md and verify header")
            return CheckResult("AGENTS.md", CheckStatus.PASS, "v5.2 family confirmed")
        except Exception as e:
            return CheckResult("AGENTS.md", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_python(self) -> CheckResult:
        required = self.config["REQUIRED_PYTHON"]
        current = sys.version_info[:3]
        if current != required:
            return CheckResult("Python Version", CheckStatus.FAIL,
                               f"Current {'.'.join(map(str, current))} != Required {'.'.join(map(str, required))}",
                               f"Install exact version: 3.11.9")
        return CheckResult("Python Version", CheckStatus.PASS, f"{'.'.join(map(str, current))} OK")

    def discover_app(self) -> Tuple[Optional[Any], CheckResult]:
        strategies = [("src.main", "app"), ("main", "app"), ("app.main", "app"),
                      ("src.api", "app"), ("api", "create_app")]
        for module_path, attr_name in strategies:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                from fastapi import FastAPI
                if hasattr(mod, attr_name):
                    app = getattr(mod, attr_name)
                    if callable(app) and not isinstance(app, FastAPI):
                        app = app()
                    if isinstance(app, FastAPI):
                        return app, CheckResult("FastAPI App", CheckStatus.PASS, f"Found at {module_path}:{attr_name}")
                for name in dir(mod):
                    obj = getattr(mod, name)
                    if isinstance(obj, FastAPI):
                        return obj, CheckResult("FastAPI App", CheckStatus.PASS, f"Found at {module_path}:{name}")
            except ImportError:
                continue
            except Exception as e:
                self.warnings.append(f"Error checking {module_path}: {e}")
        return None, CheckResult("FastAPI App", CheckStatus.FAIL, "Not found", "Check src/main/app locations")

    def check_endpoints(self, app: Optional[Any]) -> CheckResult:
        if not app:
            return CheckResult("Endpoints", CheckStatus.FAIL, "Cannot check - app not found")
        try:
            openapi = app.openapi()
            paths = set(openapi.get("paths", {}).keys())
            required = set(self.config["REQUIRED_ENDPOINTS"])
            missing = required - paths
            if missing:
                return CheckResult("Endpoints", CheckStatus.WARN, f"Missing: {missing}",
                                   f"Found sample: {sorted(paths)[:10]}")
            return CheckResult("Endpoints", CheckStatus.PASS,
                               f"{len(paths)} endpoints found; required present")
        except Exception as e:
            return CheckResult("Endpoints", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_middleware(self, app: Optional[Any]) -> CheckResult:
        if not app:
            return CheckResult("Middleware", CheckStatus.FAIL, "Cannot check - app not found")
        try:
            names = [getattr(m, "cls", type(m)).__name__ for m in app.user_middleware]
            expected = self.config["MIDDLEWARE_ORDER"]
            if names[:len(expected)] != expected:
                return CheckResult("Middleware", CheckStatus.FAIL, "Order mismatch",
                                   f"Current: {names} != Expected: {expected}")
            return CheckResult("Middleware", CheckStatus.PASS, "Order correct: " + " → ".join(expected))
        except Exception as e:
            return CheckResult("Middleware", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_services(self) -> List[CheckResult]:
        results = []
        # PostgreSQL
        try:
            import psycopg2
            dsn = os.getenv("DATABASE_URL", "postgresql://localhost/test")
            with psycopg2.connect(dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    _ = cur.fetchone()
            results.append(CheckResult("PostgreSQL", CheckStatus.PASS, "Connected"))
        except ImportError:
            results.append(CheckResult("PostgreSQL", CheckStatus.WARN, "psycopg2 not installed"))
        except Exception as e:
            results.append(CheckResult("PostgreSQL", CheckStatus.WARN, f"Connection failed: {type(e).__name__}"))
        # Redis
        try:
            import redis
            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), socket_connect_timeout=3)
            _ = r.ping()
            results.append(CheckResult("Redis", CheckStatus.PASS, "Connected"))
        except ImportError:
            results.append(CheckResult("Redis", CheckStatus.WARN, "redis-py not installed"))
        except Exception as e:
            results.append(CheckResult("Redis", CheckStatus.WARN, f"Connection failed: {type(e).__name__}"))
        return results

    def check_dependencies(self) -> CheckResult:
        try:
            import importlib.metadata
            required = ["fastapi", "pydantic", "pytest", "ruff"]
            missing, versions = [], {}
            for pkg in required:
                try:
                    versions[pkg] = importlib.metadata.version(pkg)
                except importlib.metadata.PackageNotFoundError:
                    missing.append(pkg)
            if missing:
                return CheckResult("Dependencies", CheckStatus.FAIL, f"Missing: {missing}",
                                   f"Install: pip install {' '.join(missing)}")
            return CheckResult("Dependencies", CheckStatus.PASS,
                               "Installed: " + ", ".join(f"{k}={v}" for k, v in versions.items()))
        except Exception as e:
            return CheckResult("Dependencies", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def run(self) -> int:
        print("=" * 60)
        print("Reality Map v5.0 - Environment Compliance Check")
        print("=" * 60)
        self.results.append(self.check_agents_md())
        self.results.append(self.check_python())
        self.results.append(self.check_dependencies())
        app, app_result = self.discover_app()
        self.results.append(app_result)
        if app:
            self.results.append(self.check_endpoints(app))
            self.results.append(self.check_middleware(app))
        self.results.extend(self.check_services())
        failures = sum(1 for r in self.results if r.status == CheckStatus.FAIL)
        warnings = sum(1 for r in self.results if r.status == CheckStatus.WARN)
        print()
        for r in self.results:
            print(f"{r.status.value} {r.name}: {r.message}")
            if r.details:
                print(f"   → {r.details}")
        print("\n" + "=" * 60)
        if failures > 0:
            print(f"❌ FAILED: {failures} critical issues found")
            return 1
        elif warnings > 0:
            print(f"⚠️  PASSED WITH WARNINGS: {warnings} non-critical issues")
            return 0
        else:
            print("✅ ALL CHECKS PASSED")
            return 0


if __name__ == "__main__":
    sys.exit(RealityMap().run())
