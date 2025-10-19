from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from packaging.requirements import Requirement

from .models import RequirementFile, RequirementLine


def read_requirement_file(path: Path) -> RequirementFile:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [parse_requirement_line(line) for line in text.splitlines()]
    return RequirementFile(path=path, lines=lines, original_text=text, newline=newline)


def parse_requirement_line(raw_line: str) -> RequirementLine:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        return RequirementLine(raw=raw_line, name=None)
    if stripped.lower().startswith("-r ") or stripped.lower().startswith("--requirement"):
        parts = stripped.split(maxsplit=1)
        target = parts[1] if len(parts) > 1 else ""
        return RequirementLine(
            raw=raw_line,
            name=None,
            is_include=True,
            include_target=target,
        )
    try:
        requirement = Requirement(stripped)
    except Exception:
        return RequirementLine(raw=raw_line, name=None)
    marker = str(requirement.marker) if requirement.marker else ""
    spec = str(requirement.specifier) if requirement.specifier else ""
    extras = ",".join(sorted(requirement.extras))
    return RequirementLine(
        raw=raw_line,
        name=requirement.name,
        marker=marker,
        spec=spec,
        extras=extras,
    )


def hash_plan_inputs(files: Iterable[RequirementFile]) -> str:
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda item: item.path.as_posix()):
        digest.update(file.path.as_posix().encode("utf-8"))
        digest.update(file.original_text.encode("utf-8"))
    return digest.hexdigest()
