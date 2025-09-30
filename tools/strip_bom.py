"""Strip UTF-8 BOM markers from provided files deterministically."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

BOM = "\ufeff".encode("utf-8")
TARGET_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".pyi",
    ".toml",
    ".yml",
    ".yaml",
    ".ini",
    ".json",
})
_EVIDENCE = "AGENTS.md::Determinism & CI"


def _ensure_candidates(paths: Sequence[Path]) -> list[Path]:
    candidates: list[Path] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_dir():
            for nested in path.rglob("*"):
                if nested.is_file() and nested.suffix.lower() in TARGET_EXTENSIONS:
                    candidates.append(nested)
            continue
        if path.suffix.lower() in TARGET_EXTENSIONS:
            candidates.append(path)
    return candidates


def _strip(path: Path) -> bool:
    raw = path.read_bytes()
    if not raw.startswith(BOM):
        return False
    path.write_bytes(raw[len(BOM) :])
    return True


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Files or directories to clean")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """Remove BOM markers from provided files and report the outcome."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    candidates = _ensure_candidates(args.paths)
    cleaned = 0
    for candidate in candidates:
        if _strip(candidate):
            cleaned += 1
    print(
        {
            "cleaned": cleaned,
            "total": len(candidates),
            "evidence": _EVIDENCE,
        }
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
