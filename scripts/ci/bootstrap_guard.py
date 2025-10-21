from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from scripts.deps.ensure_lock import (
    AGENTS_SENTINEL,
    DependencyManager,
    PERSIAN_AGENTS_MISSING,
    PERSIAN_GUARD_BOOTSTRAP_FAILED,
    PERSIAN_LOCK_MISSING,
)


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
        default=("packaging", "prometheus-client", "tzdata"),
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
    if not (root / AGENTS_SENTINEL).exists():
        print(PERSIAN_AGENTS_MISSING, file=sys.stderr)
        raise SystemExit(2)
    if not constraints.exists():
        print(PERSIAN_LOCK_MISSING, file=sys.stderr)
        raise SystemExit(2)

    packages = tuple(args.packages) or ("packaging", "prometheus-client", "tzdata")
    _log(
        {
            "event": "guard_bootstrap_init",
            "constraints": str(constraints),
            "packages": list(packages),
            "root": str(root),
        }
    )
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-c",
        str(constraints),
        "--no-deps",
        *packages,
    ]
    env = {**os.environ, "PIP_REQUIRE_HASHES": ""}
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        _log(
            {
                "event": "guard_bootstrap_failure",
                "status": result.returncode,
            }
        )
        print(PERSIAN_GUARD_BOOTSTRAP_FAILED, file=sys.stderr)
        raise SystemExit(2)

    manager = DependencyManager(
        root,
        correlation_id=os.getenv("CI_CORRELATION_ID"),
        metrics_path=root / "reports" / "deps-bootstrap.prom",
    )
    manager.log(
        "bootstrap_guard_success",
        constraints=str(constraints),
        packages=list(packages),
    )
    manager.write_metrics()
    _log({"event": "guard_bootstrap_complete", "status": "success"})


if __name__ == "__main__":  # pragma: no cover
    main()
