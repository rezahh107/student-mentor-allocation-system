"""Parametrised readiness probe for the packaged StudentMentorApp backend."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll the StudentMentorApp readiness endpoint.")
    parser.add_argument("--host", default="127.0.0.1", help="Backend host to probe.")
    parser.add_argument("--port", type=int, default=18000, help="Backend port to probe.")
    parser.add_argument("--path", default="/readyz", help="HTTP path for readiness.")
    parser.add_argument("--attempts", type=int, default=40, help="Maximum probe attempts.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Sleep seconds between attempts.")
    parser.add_argument("--timeout", type=float, default=1.0, help="HTTP timeout per attempt.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    url = f"http://{args.host}:{args.port}{args.path}"
    last_error: dict[str, object] | None = None
    for attempt in range(1, args.attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as response:
                status = int(response.status)
                print(f"READY[{attempt}/{args.attempts}]: {status} {url}")
                return 0 if status == 200 else 1
        except urllib.error.HTTPError as exc:
            print(f"HTTP[{attempt}/{args.attempts}]: {exc.code} {exc.reason} -> {url}")
            detail = {
                "kind": "http",
                "status": exc.code,
                "reason": exc.reason,
            }
            last_error = detail
            if exc.code >= 500:
                print(
                    "Hint: backend responded but readiness returned 5xx; "
                    f"inspect backend stderr or run 'python -X dev -m windows_service.controller run --port {args.port}' "
                    "for live logs."
                )
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            print(f"WAIT[{attempt}/{args.attempts}]: {reason}")
            last_error = {
                "kind": "network",
                "reason": str(reason),
            }
        time.sleep(max(args.sleep, 0.05))
    print("ERROR: readiness not achieved within allotted attempts.")
    summary = {
        "status": "failure",
        "attempts": args.attempts,
        "url": url,
    }
    if last_error is not None:
        summary["last_error"] = last_error
    print(json.dumps(summary, ensure_ascii=False))
    print(
        "Hints: verify StudentMentorApp.exe printed the same port, run 'python -X dev -m "
        f"windows_service.controller run --port {args.port}' for diagnostics, and ensure pip installs used "
        "'-c constraints-win.txt'."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
