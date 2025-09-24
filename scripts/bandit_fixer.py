"""ابزار ایمن برای اصلاح خودکار برخی خطاهای Bandit."""
from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

TARGET_ROOTS: tuple[str, ...] = ("src", "scripts")
B110_PATTERN = re.compile(
    r"(?P<indent>^[ \t]*)except\s+Exception(?P<alias>\s+as\s+\w+)?\s*:\s*pass\b",
    re.MULTILINE,
)


@dataclass(slots=True)
class FixSummary:
    path: Path
    transformations: List[str]


def _should_skip(path: Path) -> bool:
    parts = path.parts
    return any(part == "tests" for part in parts)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _fix_b110(text: str, *, is_ui: bool) -> tuple[str, bool]:
    """Replace ``try/except/pass`` patterns with localized logging."""

    has_logging_import = bool(re.search(r"^\s*import\s+logging\b", text, re.MULTILINE))
    added_inline_import = False
    message = (
        "رخداد خطای UI؛ پیام ثبت و پیگیری شد." if is_ui else "رخداد خطای غیرمنتظره ثبت شد."
    )

    def _replacement(match: re.Match[str]) -> str:
        nonlocal added_inline_import
        indent = match.group("indent")
        alias_group = match.group("alias") or ""
        alias_name = "exc"
        header: str
        if alias_group:
            alias_name = alias_group.strip().split()[-1]
            header = f"{indent}except Exception{alias_group}:"
        else:
            header = f"{indent}except Exception as {alias_name}:"
        body_indent = indent + "    "
        lines: list[str] = [header, "\n"]
        if not has_logging_import and not added_inline_import:
            lines.append(f"{body_indent}import logging  # nosec B110: ثبت خطا\n")
            added_inline_import = True
        lines.append(
            f"{body_indent}logging.getLogger(__name__).warning(\"{message}\", exc_info={alias_name})\n"
        )
        return "".join(lines)

    new_text, count = B110_PATTERN.subn(_replacement, text)
    return new_text, count > 0


def _fix_yaml_load(text: str) -> tuple[str, bool]:
    new_text, count = re.subn(r"\byaml\.load\(", "yaml.safe_load(", text)
    return new_text, count > 0


def _ensure_shlex_import(text: str) -> str:
    if re.search(r"^\s*import\s+shlex\b", text, re.MULTILINE):
        return text
    match = re.search(r"^\s*import\s+subprocess\b.*$", text, re.MULTILINE)
    if match:
        insert_at = match.end()
        return text[:insert_at] + "\nimport shlex" + text[insert_at:]
    return "import shlex\n" + text


def _fix_shell_usage(text: str) -> tuple[str, bool]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    replacements: list[tuple[int, int, str]] = []
    modified = False

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: D401 - نیازی به docstring نیست
            nonlocal modified
            if not isinstance(node.func, ast.Attribute):
                return
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
                return
            if node.func.attr not in {"run", "check_output"}:
                return
            shell_kw = None
            for kw in node.keywords:
                if kw.arg == "shell":
                    shell_kw = kw
                    break
            if shell_kw is None:
                return
            if not isinstance(shell_kw.value, ast.Constant) or shell_kw.value.value is not True:
                return
            if not node.args:
                return
            first_arg = node.args[0]
            if not isinstance(first_arg, (ast.Constant, ast.JoinedStr)):
                return
            cmd_segment = ast.get_source_segment(text, first_arg)
            if cmd_segment is None:
                return
            arg_texts: list[str] = []
            arg_texts.append(f"shlex.split({cmd_segment})")
            for arg in node.args[1:]:
                segment = ast.get_source_segment(text, arg)
                if segment is None:
                    return
                arg_texts.append(segment)
            check_present = False
            for kw in node.keywords:
                if kw.arg == "shell":
                    continue
                segment = ast.get_source_segment(text, kw.value)
                if segment is None:
                    return
                if kw.arg == "check":
                    check_present = True
                arg_texts.append(f"{kw.arg}={segment}")
            if not check_present:
                arg_texts.append("check=True")
            new_call = f"subprocess.{node.func.attr}(" + ", ".join(arg_texts) + ")"
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            replacements.append((start, end, new_call))
            modified = True

    _Visitor().visit(tree)
    if not replacements:
        return text, False
    new_text = text
    for start, end, value in sorted(replacements, reverse=True):
        new_text = new_text[:start] + value + new_text[end:]
    new_text = _ensure_shlex_import(new_text)
    return new_text, modified


def _apply_fixes(path: Path) -> tuple[bool, list[str]]:
    is_ui = path.as_posix().startswith("src/ui/")
    text = _load_text(path)
    transformations: list[str] = []

    new_text, changed = _fix_yaml_load(text)
    if changed:
        text = new_text
        transformations.append("B403/B506")

    new_text, changed = _fix_shell_usage(text)
    if changed:
        text = new_text
        transformations.append("B602/B603")

    new_text, changed = _fix_b110(text, is_ui=is_ui)
    if changed:
        text = new_text
        transformations.append("B110")

    if text != _load_text(path):
        _save_text(path, text)
        return True, transformations
    return False, transformations


def _iter_python_files(roots: Iterable[str]) -> Iterable[Path]:
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.py"):
            if _should_skip(path):
                continue
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="اصلاح‌گر ایمن Bandit")
    parser.add_argument("paths", nargs="*", default=TARGET_ROOTS, help="مسیرهای مورد بررسی")
    args = parser.parse_args()

    summaries: list[FixSummary] = []
    for file_path in _iter_python_files(args.paths):
        changed, tags = _apply_fixes(file_path)
        if changed:
            summaries.append(FixSummary(file_path, tags))

    if summaries:
        for summary in summaries:
            joined = ",".join(summary.transformations)
            print(f"[bandit-fixer] {summary.path}: {joined}")
    else:
        print("[bandit-fixer] تغییری اعمال نشد.")


if __name__ == "__main__":
    main()
