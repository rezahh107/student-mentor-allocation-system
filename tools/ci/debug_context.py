"""Collect debug context for flaky Windows CI runs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import hashlib
except Exception:  # pragma: no cover - fallback
    hashlib = None  # type: ignore

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None


def _hash(value: str) -> str:
    if not value:
        return ""
    if hashlib is None:
        return "***"
    return hashlib.blake2b(value.encode("utf-8"), digest_size=12).hexdigest()


def _collect_redis(namespace: str) -> Dict[str, Any]:
    if redis is None:
        return {"status": "skipped", "reason": "redis-py unavailable"}
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
        pattern = f"{namespace}:*" if namespace else "*"
        keys = [key for key in client.scan_iter(pattern, count=50)]
        sample = sorted(keys)[:10]
        client.close()
        return {
            "status": "ok",
            "url_hash": _hash(url),
            "key_count": len(keys),
            "sample": sample,
        }
    except Exception as exc:  # pragma: no cover - diagnostic only
        return {"status": "warning", "error": f"{type(exc).__name__}: {exc}"}


def _collect_env() -> Dict[str, Any]:
    interesting = [
        "GITHUB_ACTIONS",
        "RUNNER_OS",
        "PYTHONHASHSEED",
        "PYTEST_XDIST_WORKER",
        "NUMBER_OF_PROCESSORS",
    ]
    return {key: os.getenv(key, "") for key in interesting}


def _collect_paths() -> Dict[str, Any]:
    repo = Path.cwd()
    artifacts = repo / "artifacts"
    artifacts.mkdir(exist_ok=True)
    sizes: Dict[str, int] = {}
    for path in artifacts.glob("**/*"):
        if path.is_file():
            try:
                sizes[str(path.relative_to(repo))] = path.stat().st_size
            except OSError:
                continue
    return {"artifacts": sizes}


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit CI debug context")
    parser.add_argument("--reason", default="", help="Reason for capture")
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--namespace", default="windows-ci")
    parser.add_argument("--message", default="")
    parser.add_argument("--output", default="artifacts/debug-context.json")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    payload = {
        "timestamp": time.time(),
        "reason": args.reason,
        "attempt": args.attempt,
        "message": args.message,
        "env": _collect_env(),
        "paths": _collect_paths(),
        "redis": _collect_redis(args.namespace),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps({"event": "debug-context", "output": str(output_path)}))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
