"""Backward-compatible entry point to the strict weak-hash scanner."""
from __future__ import annotations

from scripts.check_no_weak_hashes import main, scan_for_weak_hashes

__all__ = ["main", "scan_for_weak_hashes"]

if __name__ == "__main__":
    raise SystemExit(main())
