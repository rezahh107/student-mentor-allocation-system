"""Simple readiness probe for the packaged StudentMentorApp backend."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request


URL = "http://127.0.0.1:18000/readyz"
ATTEMPTS = 40
SLEEP_SECONDS = 0.5


def main() -> int:
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(URL, timeout=1) as response:
                status = int(response.status)
                print(f"READY[{attempt}]: {status}")
                return 0 if status == 200 else 1
        except urllib.error.URLError as exc:
            print(f"WAIT[{attempt}]: {exc}")
        time.sleep(SLEEP_SECONDS)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

