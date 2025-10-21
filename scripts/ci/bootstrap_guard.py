from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from scripts.deps.ensure_lock import DependencyManager


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap minimal guard prerequisites deterministically",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--constraints",
        type=Path,
        default=Path("constraints-dev.txt"),
        help="Constraints file used for bootstrap installation",
    )
    parser.add_argument(
        "--packages",
        nargs="*",
        default=("packaging", "prometheus-client"),
        help="Packages that must be available before guards execute",
    )
    return parser


def _log(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    constraints = (root / args.constraints).resolve()
    manager = DependencyManager(
        root,
        correlation_id=os.getenv("CI_CORRELATION_ID"),
        metrics_path=root / "reports" / "deps-bootstrap.prom",
    )
    _log(
        {
            "event": "guard_bootstrap_init",
            "constraints": str(constraints),
            "packages": list(args.packages),
            "root": str(root),
        }
    )
    try:
        manager.bootstrap_guard_packages(constraints=constraints, packages=tuple(args.packages))
    except SystemExit:
        _log({"event": "guard_bootstrap_complete", "status": "failure"})
        raise
    _log({"event": "guard_bootstrap_complete", "status": "success"})


if __name__ == "__main__":  # pragma: no cover
    main()
