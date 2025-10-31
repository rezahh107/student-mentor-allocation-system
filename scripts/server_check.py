#!/usr/bin/env python3
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.getenv("BASE_URL", "http://127.0.0.1:8000")
REQUIRE_PUBLIC_DOCS = os.getenv("REQUIRE_PUBLIC_DOCS", "0") == "1"
METRICS_ENABLED = os.getenv("METRICS_ENDPOINT_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
}


def _hit(path, expect_codes, headers=None, attempts=3, backoff=0.3):
    url = f"{BASE}{path}"
    h = headers or {}
    last = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            last = e
            code = None
        ok = (code in expect_codes) if code is not None else False
        print(("✅" if ok else "❌") + f" {path} -> {code}")
        if ok:
            return True
        time.sleep(backoff)
    if last:
        print(f"❌ {path} error: {last}")
    return False


def main():
    passed = 0
    total = 0
    for path, expects in [
        ("/healthz", [200]),
        ("/readyz", [200, 503]),
    ]:
        total += 1
        passed += _hit(path, expects)
    doc_expected = [200] if REQUIRE_PUBLIC_DOCS else [200, 401, 403]
    for path in ("/openapi.json", "/docs", "/redoc"):
        total += 1
        passed += _hit(path, doc_expected)
    if METRICS_ENABLED:
        total += 1
        passed += _hit("/metrics", [200])
    print(f"\n📊 Result: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    sys.exit(main())
