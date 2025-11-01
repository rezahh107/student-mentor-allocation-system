#!/usr/bin/env python3
"""
Reality Map v5.0 - Production-Grade Compliance Validator
Enhanced with flexible discovery and comprehensive error handling
"""
import sys, json, os
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

class CheckStatus(Enum):
    PASS="✅"; FAIL="❌"; WARN="⚠️"; INFO="ℹ️"

@dataclass
class CheckResult:
    name:str; status:CheckStatus; message:str; details:str|None=None

class RealityMap:
    def __init__(self):
        self.results: List[CheckResult] = []; self.warnings: List[str]=[]
        self.config = {
            "REQUIRED_PYTHON": (3,11,9),
            "AGENTS_VERSION": "v5.2-LOCAL",
            "REQUIRED_ENDPOINTS": ["/health","/metrics","/api/exports"],
            "MIDDLEWARE_ORDER": ["RateLimitMiddleware","IdempotencyMiddleware","AuthMiddleware"],
            "PERF": {"export_p95":15.0,"export_p99":20.0,"memory_mb":150.0,"health_p95":0.2},
        }

    def check_agents_md(self)->CheckResult:
        try:
            p = Path("AGENTS.md")
            if not p.exists():
                return CheckResult("AGENTS.md", CheckStatus.FAIL, "File not found",
                                   "Add AGENTS.md or fetch canonical v5.2-LOCAL")
            content = p.read_text(encoding="utf-8", errors="ignore")
            expect = self.config["AGENTS_VERSION"]
            if expect not in content:
                return CheckResult("AGENTS.md", CheckStatus.FAIL,
                                   f"Version mismatch (expected {expect})",
                                   "Search file for version header")
            return CheckResult("AGENTS.md", CheckStatus.PASS, f"{expect} confirmed")
        except Exception as e:
            return CheckResult("AGENTS.md", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_python(self)->CheckResult:
        req = self.config["REQUIRED_PYTHON"]; cur = sys.version_info[:3]
        if cur != req:
            return CheckResult("Python Version", CheckStatus.FAIL,
                               f"Current {cur[0]}.{cur[1]}.{cur[2]} != Required {req[0]}.{req[1]}.{req[2]}",
                               f"Use pyenv install {req[0]}.{req[1]}.{req[2]}")
        return CheckResult("Python Version", CheckStatus.PASS, f"{cur[0]}.{cur[1]}.{cur[2]} OK")

    def discover_app(self)->Tuple[Optional[Any], CheckResult]:
        strategies=[("src.main","app"),("main","app"),("app.main","app"),("src.api","app"),("api","create_app")]
        for modpath, attr in strategies:
            try:
                import importlib; mod = importlib.import_module(modpath)
                from fastapi import FastAPI
                cand = getattr(mod, attr, None)
                if callable(cand): cand = cand()
                if isinstance(cand, FastAPI): return cand, CheckResult("FastAPI App", CheckStatus.PASS, f"Found at {modpath}:{attr}")
                for name in dir(mod):
                    obj=getattr(mod,name)
                    if isinstance(obj, FastAPI): return obj, CheckResult("FastAPI App", CheckStatus.PASS, f"Found at {modpath}:{name}")
            except ImportError: continue
            except Exception as e: self.warnings.append(f"{modpath}: {e}")
        return None, CheckResult("FastAPI App", CheckStatus.FAIL, "Not found", "Check src.main:app or main:app")

    def check_endpoints(self, app:Optional[Any])->CheckResult:
        if not app: return CheckResult("Endpoints", CheckStatus.FAIL, "Cannot check - app not found")
        try:
            paths=set(app.openapi().get("paths",{}).keys()); req=set(self.config["REQUIRED_ENDPOINTS"])
            miss=req - paths
            if miss: return CheckResult("Endpoints", CheckStatus.WARN, f"Missing: {sorted(miss)}", f"Found: {sorted(paths)[:12]}...")
            return CheckResult("Endpoints", CheckStatus.PASS, f"{len(paths)} endpoints; all required present")
        except Exception as e:
            return CheckResult("Endpoints", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_middleware(self, app:Optional[Any])->CheckResult:
        if not app: return CheckResult("Middleware", CheckStatus.FAIL, "Cannot check - app not found")
        try:
            order=[type(m).__name__ for m in app.user_middleware]
            expect=self.config["MIDDLEWARE_ORDER"]
            if order != expect:
                return CheckResult("Middleware", CheckStatus.FAIL, "Order mismatch", f"Current: {order} != Expected: {expect}")
            return CheckResult("Middleware", CheckStatus.PASS, "Order correct: " + " → ".join(expect))
        except Exception as e:
            return CheckResult("Middleware", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def check_services(self)->List[CheckResult]:
        out=[]
        try:
            import psycopg2
            dsn=os.getenv("DATABASE_URL","postgresql://localhost/postgres")
            with psycopg2.connect(dsn, connect_timeout=3) as c:
                with c.cursor() as cur: cur.execute("SELECT version()"); v=cur.fetchone()[0]
            out.append(CheckResult("PostgreSQL", CheckStatus.PASS, "Connected", v.split(',')[0]))
        except ImportError: out.append(CheckResult("PostgreSQL", CheckStatus.WARN, "psycopg2 not installed"))
        except Exception as e: out.append(CheckResult("PostgreSQL", CheckStatus.WARN, f"Connection failed: {type(e).__name__}"))
        try:
            import redis
            r=redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), socket_connect_timeout=3); info=r.info('server')
            out.append(CheckResult("Redis", CheckStatus.PASS, "Connected", f"v{info.get('redis_version','?')}"))
        except ImportError: out.append(CheckResult("Redis", CheckStatus.WARN, "redis-py not installed"))
        except Exception as e: out.append(CheckResult("Redis", CheckStatus.WARN, f"Connection failed: {type(e).__name__}"))
        return out

    def check_dependencies(self)->CheckResult:
        try:
            import importlib.metadata as md
            req=["fastapi","pydantic","pytest","ruff"]
            miss=[]; vers={}
            for p in req:
                try: vers[p]=md.version(p)
                except md.PackageNotFoundError: miss.append(p)
            if miss: return CheckResult("Dependencies", CheckStatus.FAIL, f"Missing: {miss}", f"Install: pip install {' '.join(miss)}")
            return CheckResult("Dependencies", CheckStatus.PASS, "Critical deps OK", ', '.join(f"{k}={v}" for k,v in vers.items()))
        except Exception as e:
            return CheckResult("Dependencies", CheckStatus.FAIL, f"Check failed: {type(e).__name__}", str(e))

    def run(self)->int:
        print("="*60); print("Reality Map v5.0 - Environment Compliance Check"); print("="*60)
        self.results += [self.check_agents_md(), self.check_python(), self.check_dependencies()]
        app, app_res = self.discover_app(); self.results.append(app_res)
        if app: self.results += [self.check_endpoints(app), self.check_middleware(app)]
        self.results += self.check_services()
        fails=sum(1 for r in self.results if r.status==CheckStatus.FAIL)
        warns=sum(1 for r in self.results if r.status==CheckStatus.WARN)
        for r in self.results:
            print(f"{r.status.value} {r.name}: {r.message}")
            if r.details: print(f"   → {r.details}")
        print("\n"+"="*60)
        if fails: print(f"❌ FAILED: {fails} critical issues"); return 1
        if warns: print(f"⚠️  PASSED WITH WARNINGS: {warns}"); return 0
        print("✅ ALL CHECKS PASSED"); return 0

if __name__=="__main__":
    raise SystemExit(RealityMap().run())
