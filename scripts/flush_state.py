#!/usr/bin/env python3
"""
Deterministic Redis/RedisTLS FLUSHALL for CI.

- No wall-clock assumptions
- Works for redis:// and rediss://
- TLS: either CA file or allow-insecure (for negative/interop tests)
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys

try:
    import redis  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"[fatal] redis package not importable: {e}", file=sys.stderr)
    sys.exit(2)


def _client(url: str, ca: str | None, allow_insecure: bool) -> "redis.Redis":
    kw: dict = {}
    if url.startswith("rediss://"):
        kw["ssl"] = True
        if allow_insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kw["ssl_context"] = ctx
        elif ca:
            kw["ssl_ca_certs"] = ca
    return redis.Redis.from_url(url, **kw)


def _maybe_flush(url: str | None, ca: str | None, allow_insecure: bool) -> None:
    if not url:
        return
    try:
        cli = _client(url, ca=ca, allow_insecure=allow_insecure)
        try:
            cli.ping()
        except Exception as e:
            print(f"[warn] ping failed for {url}: {e}", file=sys.stderr)
        cli.flushall()
        print(f"[ok] FLUSHALL {url}")
    except Exception as e:
        print(f"[warn] flush failed for {url}: {e}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--redis", default=os.getenv("REDIS_URL"))
    p.add_argument("--rediss", default=os.getenv("REDISS_URL"))
    p.add_argument("--ca", default=os.getenv("REDIS_TLS_CA_FILE"))
    p.add_argument(
        "--allow-insecure",
        action="store_true",
        default=(os.getenv("REDIS_TLS_ALLOW_INSECURE") == "1"),
    )
    args = p.parse_args()
    _maybe_flush(args.redis, ca=args.ca, allow_insecure=args.allow_insecure)
    _maybe_flush(args.rediss, ca=args.ca, allow_insecure=args.allow_insecure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
