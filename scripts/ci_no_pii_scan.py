"""Deterministic PII scanner for CI pipelines.

این اسکریپت به صورت دترمینیستیک کل مخزن را برای داده‌های حساس
بررسی می‌کند، یافته‌ها را به صورت HMAC ماسک کرده و در گزارش JSON
ذخیره می‌نماید. در صورت مشاهده دادهٔ حساس، خروجی اسکریپت با کد ۱
خاتمه می‌یابد تا خطوط CI متوقف شوند.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import re

from sma.phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text


class ScanError(RuntimeError):
    """خطاهای قابل پیش‌بینی در فرآیند اسکن."""


@dataclass(frozen=True)
class Finding:
    """یافتهٔ دادهٔ حساس."""

    file: Path
    line: int
    kind: str
    masked: str


@dataclass(frozen=True)
class _Pattern:
    name: str
    regex: "re.Pattern[str]"
    variant: str


SCAN_EXTENSIONS = {
    ".py",
    ".log",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".csv",
}

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "tmp",
    "tmpfile",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "reports",  # خروجی‌ها مجدداً بررسی نمی‌شوند
}


PATTERNS: Tuple[_Pattern, ...] = (
    _Pattern("national_id", re.compile(r"\b\d{10}\b"), "sanitized"),
    _Pattern("mobile", re.compile(r"09\d{9}"), "phone"),
)


def coerce_to_text(value: Optional[object]) -> str:
    """Ensure any input is converted to a safe string for scanning."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)


def compute_repo_root(start: Optional[Path] = None) -> Path:
    root = (start or Path(__file__)).resolve()
    for candidate in (root,) + tuple(root.parents):
        if (candidate / "reports").exists() and (candidate / "scripts").exists():
            return candidate
    raise ScanError("ریشهٔ مخزن شناسایی نشد؛ ساختار reports/ و scripts/ الزامی است.")


def compute_repo_salt(repo_root: Path) -> bytes:
    digest = hashlib.sha256(str(repo_root).encode("utf-8")).digest()
    return digest


def mask_secret(value: str, repo_root: Path) -> str:
    normalized = sanitize_text(value)
    secret = normalized.encode("utf-8")
    salt = compute_repo_salt(repo_root)
    digest = hmac.new(salt, secret, hashlib.sha256).hexdigest()
    return digest[:32]


def normalize_variants(text: str) -> dict[str, str]:
    sanitized = sanitize_text(text)
    return {
        "raw": text,
        "sanitized": sanitized,
        "phone": sanitize_phone(text),
    }


def iter_sensitive_tokens(text: str) -> Iterator[Tuple[str, str]]:
    variants = normalize_variants(coerce_to_text(text))
    for pattern in PATTERNS:
        haystack = variants[pattern.variant]
        for match in pattern.regex.finditer(haystack):
            yield (pattern.name, match.group(0))


def iter_candidate_files(repo_root: Path) -> Iterator[Path]:
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        yield path


def scan_file(path: Path, repo_root: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for idx, line in enumerate(handle, 1):
                for kind, value in iter_sensitive_tokens(line):
                    findings.append(
                        Finding(
                            file=path.relative_to(repo_root),
                            line=idx,
                            kind=kind,
                            masked=mask_secret(value, repo_root),
                        )
                    )
    except OSError as exc:  # pragma: no cover - خطاهای فایل نادر
        raise ScanError(f"خواندن فایل {path} با خطا مواجه شد: {exc}") from exc
    return findings


def scan_repository(repo_root: Path, files: Optional[Sequence[Path]] = None) -> List[Finding]:
    repo_root = repo_root.resolve()
    candidates = files if files is not None else list(iter_candidate_files(repo_root))
    findings: List[Finding] = []
    for file_path in candidates:
        absolute = file_path if file_path.is_absolute() else repo_root / file_path
        findings.extend(scan_file(absolute, repo_root))
    findings.sort(key=lambda item: (str(item.file), item.line, item.kind, item.masked))
    return findings


def ensure_reports_dir(repo_root: Path) -> Path:
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def atomic_write_report(repo_root: Path, findings: Sequence[Finding]) -> Path:
    reports_dir = ensure_reports_dir(repo_root)
    target = reports_dir / "pii-scan.json"
    payload = {
        "findings": [
            {
                "file": str(item.file).replace(os.sep, "/"),
                "kind": item.kind,
                "line": item.line,
                "masked": item.masked,
            }
            for item in findings
        ]
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tmp_path = target.with_suffix(".json.part")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, target)
    return target


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="اسکن مخزن برای داده‌های حساس")
    parser.add_argument(
        "paths",
        nargs="*",
        help="مسیرهای سفارشی برای اسکن؛ در صورت خالی بودن کل مخزن بررسی می‌شود.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="ریشهٔ مخزن (به طور پیش‌فرض به صورت خودکار تشخیص داده می‌شود).",
    )
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        repo_root = compute_repo_root(args.repo_root)
        if args.paths:
            files = [Path(arg) for arg in args.paths]
        else:
            files = None
        findings = scan_repository(repo_root, files)
        atomic_write_report(repo_root, findings)
    except ScanError as exc:
        print(f"خطای اسکن دادهٔ حساس: {exc}")
        return 2
    if findings:
        print("🚫 دادهٔ حساس شناسایی شد؛ گزارش در reports/pii-scan.json موجود است.")
        return 1
    print("✅ هیچ دادهٔ حساس یافت نشد؛ گزارش خالی ذخیره شد.")
    return 0


def main() -> int:  # pragma: no cover - نقطهٔ ورود اسکریپت
    return run()


if __name__ == "__main__":  # pragma: no cover - اجرای مستقیم
    raise SystemExit(main())
