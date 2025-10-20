#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from typing import Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "sma"

CORRELATION_ID = os.environ.get("SMA_CORRELATION_ID", "rewrite-imports")


def log(level: str, event: str, message: str, *, extra: dict[str, object] | None = None, stream=sys.stdout) -> None:
    payload = {
        "level": level,
        "event": event,
        "message": message,
        "correlation_id": CORRELATION_ID,
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stream)


if not SRC_ROOT.exists():
    log(
        "error",
        "rewrite_missing_namespace",
        "خطا: پوشهٔ src/sma یافت نشد؛ ابتدا migrate_shadowing را اجرا کنید.",
        stream=sys.stderr,
    )
    sys.exit(1)

FIRST_PARTY_NAMES = sorted(
    {
        path.name
        for path in SRC_ROOT.iterdir()
        if not path.name.startswith("_local_") and path.name != "__pycache__"
    }
)

IGNORE_DIRS = {".git", ".venv", "__pycache__", "build", "dist", "artifacts", "logs", "tmpfile"}

CHANGED_FILES: list[str] = []

SRC_PATTERN = re.compile(r"\b(src)(?=\.)")


def iter_python_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for path in root.rglob("*.py"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        yield path


def rewrite_content(text: str) -> tuple[str, bool]:
    changed = False
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        original_line = line
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("from "):
            parts = stripped[5:].split(" import ", 1)
            if len(parts) != 2:
                continue
            module_part, imports_part = parts
            module_part = module_part.strip()

            if module_part == "src":
                module_part = "sma"
            elif module_part.startswith("sma."):
                module_part = "sma." + module_part[4:]
            else:
                head = module_part.split(".")[0]
                if head in FIRST_PARTY_NAMES:
                    module_part = "sma." + module_part

            new_line = f"{indent}from {module_part} import {imports_part}"
            if new_line != line:
                lines[idx] = new_line
                changed = True
            continue

        if stripped.startswith("import "):
            remainder = stripped[7:]
            components = [component.strip() for component in remainder.split(",")]
            new_components: list[str] = []
            component_changed = False
            for component in components:
                if not component:
                    continue
                alias_split = component.split(" as ", 1)
                module_name = alias_split[0].strip()
                alias = alias_split[1].strip() if len(alias_split) == 2 else None

                if module_name == "src":
                    module_name = "sma"
                    component_changed = True
                elif module_name.startswith("sma."):
                    module_name = "sma." + module_name[4:]
                    component_changed = True
                else:
                    head = module_name.split(".")[0]
                    if head in FIRST_PARTY_NAMES:
                        module_name = "sma." + module_name
                        component_changed = True

                if alias:
                    new_components.append(f"{module_name} as {alias}")
                else:
                    new_components.append(module_name)

            new_line = f"{indent}import {', '.join(new_components)}"
            if component_changed:
                lines[idx] = new_line
                changed = True
            continue

        # inline replacements for any remaining sma. references
        if SRC_PATTERN.search(line):
            new_line = SRC_PATTERN.sub("sma", line)
            if new_line != line:
                lines[idx] = new_line
                changed = True

        if original_line != lines[idx]:
            changed = True

    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), changed


for py_file in iter_python_files(REPO_ROOT):
    original_text = py_file.read_text(encoding="utf-8")
    new_text, updated = rewrite_content(original_text)
    if updated and new_text != original_text:
        py_file.write_text(new_text, encoding="utf-8")
        CHANGED_FILES.append(str(py_file.relative_to(REPO_ROOT)))

violations = []
for py_file in iter_python_files(REPO_ROOT):
    text = py_file.read_text(encoding="utf-8")
    if re.search(r"\b(from|import)\s+src\b", text):
        violations.append(str(py_file.relative_to(REPO_ROOT)))

if violations:
    log(
        "error",
        "rewrite_violation",
        "خطا: الگوی ایمپورت src هنوز در فایل‌های زیر دیده می‌شود.",
        extra={"violations": sorted(violations)},
        stream=sys.stderr,
    )
    sys.exit(1)

if CHANGED_FILES:
    log(
        "info",
        "rewrite_success",
        "بازنویسی ایمپورت‌ها با موفقیت انجام شد.",
        extra={"updated": sorted(CHANGED_FILES)},
    )
else:
    log("info", "rewrite_noop", "ایمپورت تازه‌ای نیاز به بازنویسی نداشت.")
