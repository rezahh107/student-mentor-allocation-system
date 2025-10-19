"""Helper to validate and patch uvicorn entrypoints deterministically."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import typer

ENTRYPOINT_PATTERN = re.compile(r"^[A-Za-z_][\w\.]*:[A-Za-z_]\w*$")


@dataclass
class PatchResult:
    path: Path
    before: str
    after: str
    changed: bool


def validate_entrypoint(value: str) -> bool:
    """Return True if value matches uvicorn's module:attr syntax."""
    return bool(ENTRYPOINT_PATTERN.fullmatch(value))


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def patch_files(files: Iterable[Path], entrypoint: str) -> Iterable[PatchResult]:
    if not validate_entrypoint(entrypoint):
        raise ValueError("ورودی نامعتبر است؛ قالب module:attr را رعایت کنید.")
    pattern = re.compile(r"(uvicorn(?:\.exe)?\s+)(['\"]?)([A-Za-z_][\w\.]*:[A-Za-z_]\w*)(\2)")
    for file in files:
        if not file.exists():
            continue
        content = file.read_text(encoding="utf-8")
        match = pattern.search(content)
        if not match:
            yield PatchResult(file, "", "", False)
            continue

        def _replace(match: re.Match[str]) -> str:
            prefix = match.group(1)
            quote = match.group(2) or ""
            suffix = match.group(4) or ""
            return f"{prefix}{quote}{entrypoint}{suffix}"

        updated = pattern.sub(_replace, content)
        if updated != content:
            _atomic_write(file, updated)
            yield PatchResult(file, match.group(0), f"uvicorn {entrypoint}", True)
        else:
            yield PatchResult(file, match.group(0), match.group(0), False)


cli = typer.Typer(help="Validate or patch uvicorn entrypoint strings.")


@cli.command()
def check(entrypoint: str) -> None:
    """Validate entrypoint string and exit with Persian error on failure."""
    if not validate_entrypoint(entrypoint):
        typer.echo("❌ مسیر uvicorn نامعتبر است.")
        raise typer.Exit(code=1)
    typer.echo("✅ ورودی معتبر است.")


@cli.command()
def patch(
    entrypoint: str,
    files: List[Path] = typer.Argument(..., help="Files to inspect and optionally patch."),
) -> None:
    """Patch provided files with deterministic atomic writes."""
    results = list(patch_files(files, entrypoint))
    for result in results:
        status = "applied" if result.changed else "skipped"
        typer.echo(f"{result.path}: {status}")


if __name__ == "__main__":  # pragma: no cover
    cli()
