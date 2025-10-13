"""Parametrised readiness probe for the packaged StudentMentorApp backend."""

from __future__ import annotations

import argparse
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
    for attempt in range(args.attempts):
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as response:
                status = int(response.status)
                print(f"READY[{attempt}]: {status} {url}")
                return 0 if status == 200 else 1
        except urllib.error.HTTPError as exc:
            print(f"HTTP[{attempt}]: {exc.code} {exc.reason}")
            if exc.code >= 500:
                print("Hint: backend started but readiness returned 5xx; check backend logs.")
        except urllib.error.URLError as exc:
            print(f"WAIT[{attempt}]: {exc.reason}")
        time.sleep(max(args.sleep, 0.05))
    print("ERROR: readiness not achieved within allotted attempts.")
    print("Hints: verify port availability, ensure required env vars are set, confirm assets bundled.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
