from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List

from .ci_scan import analyze_ci_file, iter_ci_files
from .exporter import AuditFinding, CSVSafeWriter, render_markdown
from .fs_atomic import atomic_writer
from .logging import configure_logging, log_json, set_correlation_id
from .metrics import build_metrics
from .retry import RetryConfig, retry_async

DEFAULT_SEED = "automation_audit_seed"
HOOK_DIRECTORIES = (Path(".git/hooks"), Path(".husky"))
SCRIPT_DIRECTORIES = (Path("scripts"), Path("tools"))
CONFIG_FILES = (
    Path(".pre-commit-config.yaml"),
    Path("package.json"),
    Path("Makefile"),
    Path("tox.ini"),
    Path("noxfile.py"),
)
CSV_HEADERS = ["automation", "status", "provider", "severity", "message", "remediation"]


@dataclass
class AuditResult:
    correlation_id: str
    findings: List[AuditFinding] = field(default_factory=list)
    provider_counts: Dict[str, int] = field(default_factory=dict)
    severity_counts: Dict[str, int] = field(default_factory=dict)
    status_counts: Dict[str, int] = field(default_factory=dict)

    def add(
        self,
        *,
        automation: str,
        provider: str,
        severity: str,
        status: str,
        message: str,
        remediation: str = "",
    ) -> AuditFinding:
        finding = AuditFinding(
            provider=provider,
            severity=severity,
            message=message,
            automation=automation,
            status=status,
            remediation=remediation or "",
        )
        self.findings.append(finding)
        self.provider_counts[provider] = self.provider_counts.get(provider, 0) + 1
        self.severity_counts[severity] = self.severity_counts.get(severity, 0) + 1
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        return finding

    def to_json(self) -> Dict[str, object]:
        return {
            "correlation_id": self.correlation_id,
            "automations": [
                {
                    "name": finding.automation or finding.provider,
                    "status": finding.status,
                    "provider": finding.provider,
                    "severity": finding.severity,
                    "message": finding.message,
                    "remediation": finding.remediation or "",
                }
                for finding in self.findings
            ],
            "counters": {
                "providers": self.provider_counts,
                "severities": self.severity_counts,
                "statuses": self.status_counts,
            },
        }

    def rows(self) -> Iterator[dict[str, str]]:
        for finding in self.findings:
            yield finding.to_row()


def compute_correlation_id(root: Path, seed: str = DEFAULT_SEED) -> str:
    digest = hashlib.sha256()
    digest.update(str(root.resolve()).encode("utf-8"))
    digest.update((seed or "").encode("utf-8"))
    return digest.hexdigest()[:12]


def _audit_directory(
    result: AuditResult,
    root: Path,
    directory: Path,
    *,
    automation: str,
    provider: str,
    require_exec: bool,
    missing_severity: str = "medium",
) -> None:
    path = (root / directory).resolve()
    if not directory:
        result.add(
            automation=automation,
            provider=provider,
            severity="high",
            status="FAIL",
            message="مسیر پیکربندی نامعتبر است.",
            remediation="مسیر صحیح را تعیین کنید.",
        )
        return
    if not path.exists():
        result.add(
            automation=automation,
            provider=provider,
            severity=missing_severity,
            status="WARN",
            message=f"پوشهٔ {directory} یافت نشد.",
            remediation="در صورت نیاز پوشه را ایجاد کنید.",
        )
        return
    try:
        entries = list(path.iterdir())
    except OSError as exc:  # pragma: no cover - exercised via error handling tests
        result.add(
            automation=automation,
            provider=provider,
            severity="high",
            status="FAIL",
            message=f"خواندن پوشهٔ {directory} ممکن نشد: {exc}",
            remediation="دسترسی فایل را بررسی کنید.",
        )
        return

    invalid: list[str] = []
    for entry in entries:
        if entry.name.endswith(".sample"):
            continue
        if entry.is_file():
            check_flag = os.X_OK if require_exec else os.R_OK
            if not os.access(entry, check_flag):
                invalid.append(entry.name)
    if invalid:
        result.add(
            automation=automation,
            provider=provider,
            severity="high",
            status="FAIL",
            message="آیتم‌های غیرمجاز: " + ", ".join(sorted(invalid)),
            remediation="مجوز اجرا/خواندن را اصلاح کنید.",
        )
    else:
        result.add(
            automation=automation,
            provider=provider,
            severity="low",
            status="PASS",
            message=f"پوشهٔ {directory} بدون خطاست.",
            remediation="",
        )


def _audit_config_file(result: AuditResult, root: Path, file_path: Path) -> None:
    path = (root / file_path).resolve()
    automation = f"config:{file_path}"
    if not path.exists():
        result.add(
            automation=automation,
            provider="config",
            severity="medium",
            status="WARN",
            message=f"فایل {file_path} پیدا نشد.",
            remediation="در صورت نیاز فایل را اضافه کنید.",
        )
        return
    if not os.access(path, os.R_OK):
        result.add(
            automation=automation,
            provider="config",
            severity="high",
            status="FAIL",
            message=f"فایل {file_path} قابل‌خواندن نیست.",
            remediation="مجوزهای فایل را بازبینی کنید.",
        )
        return
    if path.stat().st_size == 0:
        result.add(
            automation=automation,
            provider="config",
            severity="medium",
            status="WARN",
            message=f"فایل {file_path} خالی است.",
            remediation="مقداردهی اولیه را انجام دهید.",
        )
        return
    result.add(
        automation=automation,
        provider="config",
        severity="low",
        status="PASS",
        message=f"فایل {file_path} آماده است.",
    )


def audit_ci_surfaces(result: AuditResult, root: Path) -> None:
    ci_files = list(iter_ci_files(root))
    if not ci_files:
        result.add(
            automation="ci",
            provider="ci",
            severity="medium",
            status="WARN",
            message="هیچ فایل CI یافت نشد.",
            remediation="پیکربندی خطوط CI را اضافه کنید.",
        )
        return

    for path in ci_files:
        relative = path.relative_to(root)

        async def analyze() -> Dict[str, List[str]]:
            return analyze_ci_file(path)

        try:
            analysis = asyncio.run(
                retry_async(analyze, config=RetryConfig(attempts=3, base_delay=0.01, jitter=0.0))
            )
        except Exception as exc:  # pragma: no cover - exercised via failure paths
            result.add(
                automation=f"ci:{relative}",
                provider="ci",
                severity="high",
                status="FAIL",
                message=f"تحلیل فایل CI ناموفق بود: {exc}",
                remediation="ساختار فایل را بررسی کنید.",
            )
            continue

        message = "مرحله‌ها: {steps}؛ متغیرها: {env}".format(
            steps=", ".join(analysis["steps"]) or "هیچ",
            env=", ".join(analysis["env"]) or "هیچ",
        )
        result.add(
            automation=f"ci:{relative}",
            provider="ci",
            severity="info",
            status="PASS",
            message=message,
        )


def audit_repo(root: Path) -> AuditResult:
    result = AuditResult(correlation_id=compute_correlation_id(root))
    for directory in HOOK_DIRECTORIES:
        _audit_directory(
            result,
            root,
            directory,
            automation=f"hooks:{directory}",
            provider="hooks",
            require_exec=True,
            missing_severity="medium",
        )
    for directory in SCRIPT_DIRECTORIES:
        _audit_directory(
            result,
            root,
            directory,
            automation=f"dir:{directory}",
            provider="fs",
            require_exec=False,
            missing_severity="low",
        )
    for file_path in CONFIG_FILES:
        _audit_config_file(result, root, file_path)
    audit_ci_surfaces(result, root)
    return result


def write_reports(root: Path, result: AuditResult, *, with_markdown: bool, with_csv: bool) -> None:
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "automation_audit.json"
    md_path = reports_dir / "automation_audit.md"
    csv_path = reports_dir / "automation_audit.csv"

    with atomic_writer(json_path, mode="w", encoding="utf-8") as handle:
        json.dump(result.to_json(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if with_markdown:
        markdown = render_markdown(result.findings)
        with atomic_writer(md_path, mode="w", encoding="utf-8") as handle:
            handle.write(markdown)
    if with_csv:
        writer = CSVSafeWriter(csv_path, headers=CSV_HEADERS)
        writer.write(result.rows())


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automation audit CLI")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--seed", type=str, default=DEFAULT_SEED)
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument("--csv", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    root = Path(args.root or Path.cwd()).resolve()
    correlation_id = compute_correlation_id(root, args.seed)
    set_correlation_id(correlation_id)
    metrics = build_metrics()
    metrics.audit_runs.inc()
    result = audit_repo(root)
    if any(finding.status == "FAIL" for finding in result.findings):
        metrics.audit_failures.inc()
    log_json("audit_completed", findings=len(result.findings), correlation_id=correlation_id)
    write_reports(root, result, with_markdown=not args.no_markdown, with_csv=args.csv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
