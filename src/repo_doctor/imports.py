from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from .io_utils import atomic_write, ensure_crlf
from .logging_utils import JsonLogger
from .metrics import DoctorMetrics
from .report import DoctorRunReport
from .retry import RetryPolicy
from .state import DebugBundle

IMPORT_PATTERN = re.compile(r"^(?P<prefix>\s*from\s+)(?P<module>[\w\.]+)(?P<suffix>\s+import\s+.+)$")
SIMPLE_IMPORT_PATTERN = re.compile(r"^(?P<prefix>\s*import\s+)(?P<modules>[\w\.,\s]+)$")


@dataclass(slots=True)
class ImportIssue:
    file: pathlib.Path
    original: str
    updated: str


class ImportDoctor:
    def __init__(
        self,
        *,
        root: pathlib.Path,
        apply: bool,
        logger: JsonLogger,
        metrics: DoctorMetrics,
        retry: RetryPolicy,
        debug: DebugBundle,
        packages: Sequence[str] | None = None,
    ) -> None:
        self.root = root
        self.should_apply = apply
        self.logger = logger
        self.metrics = metrics
        self.retry = retry
        self.debug = debug
        self.packages = tuple(sorted(packages or self._discover_packages()))
        self._last_issues: List[ImportIssue] = []
        self._last_missing_inits: List[pathlib.Path] = []

    # ------------------------------------------------------------------
    def _discover_packages(self) -> List[str]:
        src_dir = self.root / "src"
        names: List[str] = []
        if not src_dir.exists():
            return names
        for entry in src_dir.iterdir():
            if entry.name.startswith("__"):
                continue
            if entry.is_dir() and any(entry.glob("**/*.py")):
                names.append(entry.name)
            elif entry.suffix == ".py":
                names.append(entry.stem)
        return names

    def scan(self) -> DoctorRunReport:
        report = DoctorRunReport(name="imports")
        src_dir = self.root / "src"
        issues: List[ImportIssue] = []
        for file in src_dir.rglob("*.py"):
            if file.name == "__init__.py":
                continue
            original = file.read_text(encoding="utf-8")
            updated = self._rewrite_content(original)
            if updated != original:
                issues.append(ImportIssue(file=file, original=original, updated=updated))
                report.add_finding(file=str(file), action="rewrite")
        missing_inits = self._missing_init_files()
        for init_path in missing_inits:
            report.add_finding(file=str(init_path), action="add_init")
        report.metrics["issues"] = len(issues)
        report.metrics["missing_inits"] = len(missing_inits)
        self.debug.record("import_scan", {
            "issues": [issue.file.as_posix() for issue in issues],
            "missing_inits": [path.as_posix() for path in missing_inits],
        })
        report.findings.extend(
            {"file": issue.file.as_posix(), "action": "rewrite"} for issue in issues
        )
        report.findings.extend(
            {"file": path.as_posix(), "action": "add_init"} for path in missing_inits
        )
        self._last_issues = issues
        self._last_missing_inits = missing_inits
        return report

    def apply(self, report: DoctorRunReport) -> None:
        issues = self._last_issues
        missing_inits = self._last_missing_inits
        if not self.should_apply:
            self.logger.info("Dry-run; skipping import fixes")
            return
        delta_log: Dict[str, Dict[str, str]] = {}
        for issue in issues:
            backup_path = issue.file.with_suffix(issue.file.suffix + ".bak")
            if not backup_path.exists():
                backup_path.write_text(issue.original, encoding="utf-8")
            atomic_write(issue.file, ensure_crlf(issue.updated), newline="")
            delta_log[str(issue.file)] = {
                "from": issue.original,
                "to": issue.updated,
            }
        for init_path in missing_inits:
            if not init_path.exists():
                atomic_write(init_path, ensure_crlf(""), newline="")
        if delta_log:
            delta_path = self.root / "reports" / "import_delta.json"
            atomic_write(delta_path, ensure_crlf(json.dumps(delta_log, ensure_ascii=False, indent=2)), newline="\n")
            self.logger.info("Wrote import delta", path=str(delta_path))

    # ------------------------------------------------------------------
    def _rewrite_content(self, content: str) -> str:
        lines = content.splitlines()
        rewritten: List[str] = []
        for line in lines:
            rewritten.append(self._rewrite_line(line))
        result = "\n".join(rewritten)
        if content.endswith("\n"):
            result += "\n"
        return result

    def _rewrite_line(self, line: str) -> str:
        from_match = IMPORT_PATTERN.match(line)
        if from_match:
            module = from_match.group("module")
            if module.startswith("src.") or module.startswith("."):
                return line
            base = module.split(".")[0]
            if base in self.packages:
                module = f"src.{module}"
                return f"{from_match.group('prefix')}{module}{from_match.group('suffix')}"
            return line
        simple_match = SIMPLE_IMPORT_PATTERN.match(line)
        if simple_match:
            modules = [part.strip() for part in simple_match.group("modules").split(",")]
            rewritten_modules = []
            changed = False
            for module in modules:
                if module.startswith("src.") or module.startswith("."):
                    rewritten_modules.append(module)
                    continue
                base = module.split(".")[0]
                if base in self.packages:
                    rewritten_modules.append(f"src.{module}")
                    changed = True
                else:
                    rewritten_modules.append(module)
            if changed:
                return f"{simple_match.group('prefix')}{', '.join(rewritten_modules)}"
        return line

    def _missing_init_files(self) -> List[pathlib.Path]:
        src_dir = self.root / "src"
        missing: List[pathlib.Path] = []
        for directory in src_dir.rglob("*"):
            if not directory.is_dir():
                continue
            if not any(directory.glob("*.py")):
                continue
            init_path = directory / "__init__.py"
            if not init_path.exists():
                missing.append(init_path)
        return missing
