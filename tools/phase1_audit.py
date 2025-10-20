#!/usr/bin/env python3
"""Phase-1 audit CLI for the student mentor allocation system.

Command examples::

    python tools/phase1_audit.py --repo . --out reports/phase1_audit.json --md reports/phase1_audit.md
    python tools/phase1_audit.py --repo . --strict-missing-deps
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass
class CheckExecutionResult:
    """Represents the outcome of a single requirement evaluation."""

    passed: bool
    evidence: str
    hint_override: Optional[str] = None
    severity_override: Optional[str] = None


@dataclass
class RequirementCheck:
    """Metadata and execution hook for a requirement."""

    id: str
    title: str
    hint: str
    severity: str
    executor: Callable[["AuditContext"], CheckExecutionResult]


@dataclass
class CheckResult:
    """Rendered result for reporting."""

    id: str
    title: str
    result: str
    evidence: str
    hint: str
    severity: str


@dataclass
class TestResult:
    """Holds pytest execution details."""

    exit_code: int
    duration_s: float
    output: str
    passed: int
    failed: int
    errors: int
    coverage_present: bool
    executed_tests: list[str]
    skipped_tests: list[dict[str, str]]
    command: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class AuditContext:
    """Provides cached repository access for requirement checks."""

    repo: Path
    _cache: dict[Path, str] = field(default_factory=dict)

    def read_text(self, path: Path) -> str:
        """Return UTF-8 content for *path* from cache when available."""

        if path not in self._cache:
            self._cache[path] = path.read_text(encoding="utf-8")
        return self._cache[path]

    def glob(self, pattern: str) -> Iterable[Path]:
        """Yield files matching *pattern* relative to the repository root."""

        return self.repo.glob(pattern)

    def rglob(self, pattern: str) -> Iterable[Path]:
        """Recursively yield files matching *pattern*."""

        return self.repo.rglob(pattern)


TEST_MODULES = [
    "tests/test_logging_payloads.py",
    "tests/test_normalization_branches.py",
    "tests/test_normalization.py",
    "tests/test_normalization_checksum.py",
]

DEPENDENCY_HINTS = {
    "hypothesis": "کتابخانه hypothesis را نصب کنید: pip install hypothesis",
    "pytest_cov": "پلاگین pytest-cov را نصب کنید: pip install pytest-cov",
}


def detect_dependencies() -> dict[str, bool]:
    """Return availability flags for optional test-time dependencies."""

    availability: dict[str, bool] = {}
    for name in ("hypothesis", "pytest_cov"):
        availability[name] = importlib.util.find_spec(name) is not None
    return availability


def categorize_test_modules(repo: Path) -> tuple[list[str], list[str], list[str]]:
    """Partition test modules into plain, hypothesis-based, and missing."""

    plain: list[str] = []
    requires_hypothesis: list[str] = []
    missing: list[str] = []
    pattern = re.compile(r"^\s*(?:from|import)\s+hypothesis", re.MULTILINE)
    for relative in TEST_MODULES:
        candidate = repo / relative
        if not candidate.exists():
            missing.append(relative)
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            requires_hypothesis.append(relative)
        else:
            plain.append(relative)
    return plain, requires_hypothesis, missing


def _literal_assign(module: ast.Module, name: str) -> Optional[object]:
    """Return the literal value assigned to ``name`` if statically known."""

    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                try:
                    return ast.literal_eval(node.value)
                except Exception:  # pragma: no cover - defensive path
                    return None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name and node.value is not None:
                try:
                    return ast.literal_eval(node.value)
                except Exception:  # pragma: no cover - defensive path
                    return None
    return None


def check_gender_enums(context: AuditContext) -> CheckExecutionResult:
    """Ensure gender enums include Persian labels and enforcement."""

    enums_path = context.repo / "src/core/enums.py"
    normalize_path = context.repo / "src/core/normalize.py"
    if not enums_path.exists() or not normalize_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/enums.py or src/core/normalize.py is missing.",
        )
    enums_text = context.read_text(enums_path)
    normalize_text = context.read_text(normalize_path)
    female_match = re.search(r"\"زن\"\s*:\s*0", enums_text)
    male_match = re.search(r"\"مرد\"\s*:\s*1", enums_text)
    literal_enforcement = re.search(r"Literal\s*\[\s*0\s*,\s*1\s*\]", normalize_text)
    if female_match and male_match and literal_enforcement:
        evidence = "Found Persian gender mappings and Literal[0, 1] enforcement."
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "Missing gender mapping or enforcement literal in normalization logic."
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_counter_prefix(context: AuditContext) -> CheckExecutionResult:
    """Verify downstream counter prefixes for gender mapping."""

    enums_path = context.repo / "src/core/enums.py"
    if not enums_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/enums.py is missing for counter prefix lookup.",
        )
    module = ast.parse(context.read_text(enums_path))
    mapping = _literal_assign(module, "COUNTER_PREFIX")
    if isinstance(mapping, dict):
        male = mapping.get(1)
        female = mapping.get(0)
        if male == 357 and female == 373:
            evidence = "COUNTER_PREFIX exposes {1: 357, 0: 373}."
            return CheckExecutionResult(passed=True, evidence=evidence)
    return CheckExecutionResult(
        passed=False,
        evidence="COUNTER_PREFIX does not map {1:357, 0:373} exactly.",
    )


def check_reg_status(context: AuditContext) -> CheckExecutionResult:
    """Ensure registration status maps to {0,1,3} including Hakmat."""

    enums_path = context.repo / "src/core/enums.py"
    if not enums_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/enums.py is missing for reg_status verification.",
        )
    module = ast.parse(context.read_text(enums_path))
    mapping = _literal_assign(module, "REG_STATUS_NORMALIZATION_MAP")
    if isinstance(mapping, dict):
        values = set(mapping.values())
        hakmat_target = None
        for key, value in mapping.items():
            if isinstance(key, str) and key.lower() == "hakmat":
                hakmat_target = value
                break
        if values <= {0, 1, 3} and hakmat_target == 3:
            evidence = "REG_STATUS_NORMALIZATION_MAP restricts to {0,1,3} with Hakmat→3."
            return CheckExecutionResult(passed=True, evidence=evidence)
    return CheckExecutionResult(
        passed=False,
        evidence="REG_STATUS_NORMALIZATION_MAP missing Hakmat→3 or extra values.",
    )


def check_reg_center(context: AuditContext) -> CheckExecutionResult:
    """Ensure registration center normalization only accepts {0,1,2}."""

    enums_path = context.repo / "src/core/enums.py"
    if not enums_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/enums.py is missing for reg_center verification.",
        )
    module = ast.parse(context.read_text(enums_path))
    mapping = _literal_assign(module, "REG_CENTER_NORMALIZATION_MAP")
    if isinstance(mapping, dict) and set(mapping.values()) == {0, 1, 2}:
        evidence = "REG_CENTER_NORMALIZATION_MAP strictly maps to {0,1,2}."
        return CheckExecutionResult(passed=True, evidence=evidence)
    return CheckExecutionResult(
        passed=False,
        evidence="REG_CENTER_NORMALIZATION_MAP does not restrict to {0,1,2}.",
    )


def check_mobile_rules(context: AuditContext) -> CheckExecutionResult:
    """Confirm mobile normalization covers digits, prefixes, regex, and masking."""

    normalize_path = context.repo / "src/core/normalize.py"
    logging_path = context.repo / "src/core/logging_utils.py"
    missing = [
        str(path)
        for path in (normalize_path, logging_path)
        if not path.exists()
    ]
    if missing:
        evidence = f"Missing required files for mobile validation: {', '.join(missing)}"
        return CheckExecutionResult(passed=False, evidence=evidence)
    normalize_text = context.read_text(normalize_path)
    logging_text = context.read_text(logging_path)
    digits_present = bool(re.search(r"[۰-۹٠-٩]", normalize_text))
    prefix_present = all(token in normalize_text for token in ["0098", "_normalize_mobile_prefix"])
    regex_present = bool(re.search(r"\^09\\d\{9\}\$", normalize_text))
    mask_present = "09*******" in logging_text
    missing_flags = []
    if not digits_present:
        missing_flags.append("digit canonicalization")
    if not prefix_present:
        missing_flags.append("prefix normalization")
    if not regex_present:
        missing_flags.append("strict ^09\\d{9}$ regex")
    if not mask_present:
        missing_flags.append("log masking 09*******XX")
    if not missing_flags:
        evidence = "Mobile logic normalizes digits, prefixes, regex, and masks logs."
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "Missing mobile compliance pieces: " + ", ".join(missing_flags)
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_national_id(context: AuditContext) -> CheckExecutionResult:
    """Verify national ID normalization enforces a 10 digit regex."""

    normalize_path = context.repo / "src/core/normalize.py"
    if not normalize_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/normalize.py is missing for national ID validation.",
        )
    text = context.read_text(normalize_path)
    pattern_present = bool(re.search(r"re\.fullmatch\(r\"\\d\{10\}\"", text))
    function_present = "def normalize_national_id" in text
    if pattern_present and function_present:
        evidence = 'normalize_national_id enforces re.fullmatch(r"\\d{10}").'
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "normalize_national_id missing strict 10-digit regex enforcement."
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_logging_salt(context: AuditContext) -> CheckExecutionResult:
    """Ensure logging hashes use environment-aware salt selection."""

    logging_path = context.repo / "src/core/logging_utils.py"
    if not logging_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/logging_utils.py missing for hashing rules.",
        )
    text = context.read_text(logging_path)
    env_tokens = all(token in text for token in ["APP_ENV", "PII_HASH_SALT", "TEST_HASH_SALT"])
    salt_logic = "_current_salt" in text and "_TEST_ENVIRONMENTS" in text
    if env_tokens and salt_logic:
        evidence = "_current_salt uses APP_ENV with PII_HASH_SALT/TEST_HASH_SALT overrides."
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "Missing APP_ENV-aware salt logic for national ID hashing."
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_student_type_derivation(context: AuditContext) -> CheckExecutionResult:
    """Confirm student_type is derived and inbound values trigger warnings."""

    models_path = context.repo / "src/core/models.py"
    normalize_path = context.repo / "src/core/normalize.py"
    if not models_path.exists() or not normalize_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="Required models/normalize modules missing for student_type checks.",
        )
    models_text = context.read_text(models_path)
    normalize_text = context.read_text(normalize_path)
    derivation_call = "derive_student_type(" in models_text
    ignore_warning = "student_type.ignored_input" in models_text
    roster_logic = "def derive_student_type" in normalize_text
    if derivation_call and ignore_warning and roster_logic:
        evidence = (
            "student_type derived via derive_student_type and inbound values logged as warnings."
        )
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "student_type not derived solely from roster or missing warning for inbound input."
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_dto_strict_aliases(context: AuditContext) -> CheckExecutionResult:
    """Verify DTO strictness, pydantic v2 usage, and backward compatibility aliases."""

    models_path = context.repo / "src/core/models.py"
    if not models_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/models.py missing for DTO validation.",
        )
    text = context.read_text(models_path)
    config_dict = bool(re.search(r"model_config\s*=\s*ConfigDict\(.*extra=\"forbid\"", text))
    populate_flag = "populate_by_name=True" in text
    field_validator_usage = "@field_validator" in text
    alias_tokens = all(token in text for token in ["_GENDER_ALIASES", "sex", "_REG_STATUS_ALIASES", "status", "_REG_CENTER_ALIASES", "center"])
    persian_errors = bool(re.search(r"[آ-ی]", text))
    if config_dict and populate_flag and field_validator_usage and alias_tokens and persian_errors:
        evidence = (
            "StudentNormalized uses ConfigDict(strict), field_validator hooks, aliases, and Persian errors."
        )
        return CheckExecutionResult(passed=True, evidence=evidence)
    missing_bits = []
    if not config_dict:
        missing_bits.append("ConfigDict(... extra='forbid')")
    if not populate_flag:
        missing_bits.append("populate_by_name=True")
    if not field_validator_usage:
        missing_bits.append("pydantic field_validator hooks")
    if not alias_tokens:
        missing_bits.append("alias tuples containing sex/status/center")
    if not persian_errors:
        missing_bits.append("Persian error messages")
    evidence = "DTO missing: " + ", ".join(missing_bits)
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_logging_payload_schema(context: AuditContext) -> CheckExecutionResult:
    """Ensure warning payload schema contains the four required keys."""

    logging_path = context.repo / "src/core/logging_utils.py"
    if not logging_path.exists():
        return CheckExecutionResult(
            passed=False,
            evidence="src/core/logging_utils.py missing for payload schema.",
        )
    text = context.read_text(logging_path)
    pattern = re.compile(
        r"payload\s*:\s*dict\[[^]]+\]\s*=\s*\{[^}]*\"code\"[^}]*\"sample\"[^}]*\"mobile_mask\"[^}]*\"nid_hash\"",
        re.DOTALL,
    )
    if pattern.search(text):
        evidence = "log_norm_error payload restricts to code/sample/mobile_mask/nid_hash."
        return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "Structured logging payload missing required keys or includes extras."
    return CheckExecutionResult(passed=False, evidence=evidence)


def check_no_raw_pii_logging(context: AuditContext) -> CheckExecutionResult:
    """Detect direct logging of raw national IDs or mobile numbers."""

    suspicious_patterns = [
        r"LOGGER\.warning\([^)]*national_id",
        r"LOGGER\.warning\([^)]*09\\d{9}",
        r"\"national_id\"\s*:\s*old",
        r"\"mobile\"\s*:\s*old",
    ]
    matches: list[str] = []
    for path in context.rglob("*.py"):
        text = context.read_text(path)
        for pattern in suspicious_patterns:
            if re.search(pattern, text):
                matches.append(f"{path.relative_to(context.repo)} -> {pattern}")
    if matches:
        evidence = "Potential raw PII logging detected: " + "; ".join(matches)
        return CheckExecutionResult(
            passed=False,
            evidence=evidence,
            severity_override="warning",
            hint_override="بررسی کنید که لاگ‌ها اطلاعات حساس را پنهان کنند.",
        )
    evidence = "No direct LOGGER.warning usage with raw national_id/mobile detected."
    return CheckExecutionResult(passed=True, evidence=evidence)


def check_tests_exist(context: AuditContext) -> CheckExecutionResult:
    """Ensure mandated pytest modules exist."""

    required = [
        context.repo / "tests/test_logging_payloads.py",
        context.repo / "tests/test_normalization_branches.py",
        context.repo / "tests/test_normalization.py",
        context.repo / "tests/test_normalization_checksum.py",
    ]
    missing = [str(path.relative_to(context.repo)) for path in required if not path.exists()]
    if missing:
        evidence = "Missing required test files: " + ", ".join(missing)
        hint = "فایل تست موجود نیست؛ آن را ایجاد یا بازیابی کنید."
        return CheckExecutionResult(passed=False, evidence=evidence, hint_override=hint)
    evidence = "All mandated pytest modules are present."
    return CheckExecutionResult(passed=True, evidence=evidence)


def check_tests_cover_locales(context: AuditContext) -> CheckExecutionResult:
    """Verify tests cover Persian/Arabic digits, prefixes, and null-like inputs."""

    test_files = [
        context.repo / "tests/test_normalization.py",
        context.repo / "tests/test_logging_payloads.py",
    ]
    missing = [str(path.relative_to(context.repo)) for path in test_files if not path.exists()]
    if missing:
        evidence = "Cannot inspect locale coverage; missing: " + ", ".join(missing)
        hint = "فایل تست موجود نیست؛ موارد مرزی را پوشش دهید."
        return CheckExecutionResult(passed=False, evidence=evidence, hint_override=hint)
    aggregate_text = "\n".join(context.read_text(path) for path in test_files)
    patterns = {
        "Persian digits": "۰",
        "Arabic digits": "٠",
        "+98 prefix": "+98",
        "0098 prefix": "0098",
        "Hakmat variant": "Hakmat",
        "Null handling": "None",
    }
    missing_labels = [label for label, token in patterns.items() if token not in aggregate_text]
    if missing_labels:
        evidence = "Tests missing coverage for: " + ", ".join(missing_labels)
        hint = "سناریوهای ذکر شده را به تست‌ها اضافه کنید."
        return CheckExecutionResult(passed=False, evidence=evidence, hint_override=hint)
    evidence = "Tests exercise Persian/Arabic digits, prefixes, Hakmat, and null handling."
    return CheckExecutionResult(passed=True, evidence=evidence)


def check_phone_regex_presence(context: AuditContext) -> CheckExecutionResult:
    """Detect the strict ^09\\d{9}$ pattern within normalization code."""

    for path in [context.repo / "src/core/normalize.py", context.repo / "src/core/models.py"]:
        if not path.exists():
            continue
        if re.search(r"\^09\\d\{9\}\$", context.read_text(path)):
            evidence = f"Strict ^09\\d{{9}}$ regex found in {path.relative_to(context.repo)}."
            return CheckExecutionResult(passed=True, evidence=evidence)
    evidence = "Strict ^09\\d{9}$ regex not found in normalization code."
    return CheckExecutionResult(passed=False, evidence=evidence)


def gather_checks() -> list[RequirementCheck]:
    """Return ordered requirement checks per specification."""

    return [
        RequirementCheck(
            id="REQ-GENDER-0001",
            title="Gender enums 0/1",
            hint="نقشه جنسیت را با برچسب‌های زن/مرد و اعتبارسنجی سخت‌گیرانه تکمیل کنید.",
            severity="error",
            executor=check_gender_enums,
        ),
        RequirementCheck(
            id="REQ-COUNTER-0002",
            title="Counter prefixes 357/373",
            hint="مقدار COUNTER_PREFIX را به {1:357, 0:373} تنظیم کنید.",
            severity="error",
            executor=check_counter_prefix,
        ),
        RequirementCheck(
            id="REQ-STATUS-0003",
            title="reg_status domain",
            hint="تنها مقادیر ۰/۱/۳ و نگاشت Hakmat→3 را در وضعیت ثبت‌نام بپذیرید.",
            severity="error",
            executor=check_reg_status,
        ),
        RequirementCheck(
            id="REQ-CENTER-0004",
            title="reg_center domain",
            hint="ثبت‌نام مرکز را به مقادیر ۰/۱/۲ محدود کنید.",
            severity="error",
            executor=check_reg_center,
        ),
        RequirementCheck(
            id="REQ-MOBILE-0005",
            title="Mobile canonicalization",
            hint="نرمال‌سازی موبایل باید ارقام فارسی/عربی، پیش‌شماره و الگوی ^09 را پوشش دهد.",
            severity="error",
            executor=check_mobile_rules,
        ),
        RequirementCheck(
            id="REQ-NID-0006",
            title="National ID format",
            hint="کد ملی را با الگوی دقیق \\d{10} بررسی کنید.",
            severity="error",
            executor=check_national_id,
        ),
        RequirementCheck(
            id="REQ-LOG-0007",
            title="Hash salt policy",
            hint="قوانین APP_ENV و TEST_HASH_SALT را برای هش PII پیاده‌سازی کنید.",
            severity="error",
            executor=check_logging_salt,
        ),
        RequirementCheck(
            id="REQ-STUDENTTYPE-0008",
            title="Derived student_type",
            hint="student_type را صرفاً از roster مشتق کنید و ورودی خام را نادیده بگیرید.",
            severity="error",
            executor=check_student_type_derivation,
        ),
        RequirementCheck(
            id="REQ-PYDANTIC-0009",
            title="DTO strict + aliases",
            hint="ConfigDict سخت‌گیرانه و نام‌های مستعار sex/status/center را در DTO نگه دارید.",
            severity="error",
            executor=check_dto_strict_aliases,
        ),
        RequirementCheck(
            id="REQ-LOGSCHEMA-0010",
            title="Logging payload schema",
            hint="ساختار لاگ باید فقط کلیدهای code/sample/mobile_mask/nid_hash را داشته باشد.",
            severity="error",
            executor=check_logging_payload_schema,
        ),
        RequirementCheck(
            id="REQ-LOGSAFE-0011",
            title="No raw PII logs",
            hint="بررسی کنید که لاگ‌ها شماره موبایل یا کد ملی خام چاپ نکنند.",
            severity="warning",
            executor=check_no_raw_pii_logging,
        ),
        RequirementCheck(
            id="REQ-TESTS-0012",
            title="Mandated tests present",
            hint="تمام فایل‌های تست مشخص‌شده را اضافه کنید.",
            severity="error",
            executor=check_tests_exist,
        ),
        RequirementCheck(
            id="REQ-TESTS-0013",
            title="Locale coverage in tests",
            hint="تست‌ها باید ارقام فارسی/عربی و پیش‌شماره‌های +98/0098 را پوشش دهند.",
            severity="error",
            executor=check_tests_cover_locales,
        ),
        RequirementCheck(
            id="REQ-MOBILE-REGEX-0014",
            title="Phone regex present",
            hint="الگوی ^09\\d{9}$ را در کد نرمال‌سازی تعریف کنید.",
            severity="error",
            executor=check_phone_regex_presence,
        ),
    ]


def execute_checks(context: AuditContext) -> list[CheckResult]:
    """Run all requirement checks and capture structured results."""

    results: list[CheckResult] = []
    for check in gather_checks():
        try:
            execution = check.executor(context)
        except Exception as exc:  # pragma: no cover - defensive path
            evidence = f"Check raised exception: {exc}"
            results.append(
                CheckResult(
                    id=check.id,
                    title=check.title,
                    result="fail",
                    evidence=evidence,
                    hint=check.hint,
                    severity=check.severity,
                )
            )
            continue
        hint = execution.hint_override or check.hint
        severity = execution.severity_override or check.severity
        result = "pass" if execution.passed else "fail"
        results.append(
            CheckResult(
                id=check.id,
                title=check.title,
                result=result,
                evidence=execution.evidence,
                hint=hint,
                severity=severity,
            )
        )
    return results


def downgrade_checks_for_dependency_skips(
    checks: list[CheckResult], skipped_tests: list[dict[str, str]]
) -> None:
    """Downgrade relevant findings when dependent tests could not run."""

    if not skipped_tests:
        return
    missing_hypothesis = any(entry.get("missing") == "hypothesis" for entry in skipped_tests)
    if not missing_hypothesis:
        return
    for check in checks:
        if check.id == "REQ-TESTS-0013" and check.result == "fail":
            check.severity = "warning"
            check.hint = (
                "اجرای کامل این بررسی نیازمند کتابخانه hypothesis است؛ برای سخت‌گیری کامل آن را نصب کنید."
            )
            check.evidence = (
                check.evidence
                + " (بررسی کامل پس از فعال‌سازی تست‌های Hypothesis انجام می‌شود.)"
            )


def parse_pytest_counts(output: str) -> tuple[int, int, int]:
    """Extract passed, failed, and error counts from pytest output."""

    def _extract(pattern: str) -> int:
        match = re.search(pattern, output)
        return int(match.group(1)) if match else 0

    passed = _extract(r"(\d+)\s+passed")
    failed = _extract(r"(\d+)\s+failed")
    errors = _extract(r"(\d+)\s+errors?")
    return passed, failed, errors


def run_tests(
    repo: Path,
    tests_to_run: list[str],
    coverage_enabled: bool,
    skipped: list[dict[str, str]],
) -> TestResult:
    """Execute pytest for the selected modules and capture diagnostics."""

    if not tests_to_run:
        message = "Pytest execution skipped: no runnable tests after dependency filtering."
        return TestResult(
            exit_code=0,
            duration_s=0.0,
            output=message,
            passed=0,
            failed=0,
            errors=0,
            coverage_present=False,
            executed_tests=[],
            skipped_tests=list(skipped),
            command=[],
            notes=["هیچ تستی بدون وابستگی‌های اختیاری قابل اجرا نبود."],
        )

    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = ["pytest"]
    if coverage_enabled:
        command.extend(
            [
                "-p",
                "pytest_cov",
                "--cov=sma.core.normalize",
                "--cov=sma.core.models",
                "--cov-report=term-missing",
            ]
        )
    command.extend(tests_to_run)

    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    duration = time.perf_counter() - start
    output = (completed.stdout or "") + (completed.stderr or "")
    passed, failed, errors = parse_pytest_counts(output)
    coverage_present = False
    if coverage_enabled:
        coverage_present = bool(
            re.search(r"src/core/(?:normalize|models)", output)
            or "Coverage" in output
            or "term-missing" in output
        )
    exit_code = completed.returncode
    notes: list[str] = []
    if (
        exit_code != 0
        and skipped
        and coverage_enabled
        and (
            "Coverage failure" in output
            or "Required test coverage" in output
            or "Required test coverage of" in output
        )
        and failed == 0
        and errors == 0
    ):
        exit_code = 0
        notes.append(
            "آستانه‌ی پوشش به دلیل اجرای بخشی از تست‌ها برآورده نشد؛ با نصب وابستگی‌های اختیاری قابل رفع است."
        )
    return TestResult(
        exit_code=exit_code,
        duration_s=duration,
        output=output,
        passed=passed,
        failed=failed,
        errors=errors,
        coverage_present=coverage_present,
        executed_tests=list(tests_to_run),
        skipped_tests=list(skipped),
        command=command,
        notes=notes,
    )


def render_markdown(
    checks: list[CheckResult],
    tests: TestResult,
    json_path: Path,
    md_path: Optional[Path],
    environment: dict[str, object],
) -> str:
    """Create the Markdown summary for both stdout and optional file output."""

    lines = ["# Phase-1 Audit Summary", ""]
    overall_tests = "PASS" if tests.exit_code == 0 else "FAIL"
    coverage_note = "✅" if tests.coverage_present else "⚠️"
    lines.append(
        f"*Tests:* **{overall_tests}** (exit={tests.exit_code}, duration={tests.duration_s:.2f}s, "
        f"passed={tests.passed}, failed={tests.failed}, errors={tests.errors}, coverage={coverage_note})"
    )
    lines.append("")
    lines.append("## Dependencies")
    lines.append("")
    lines.append("| Dependency | Status | Hint |")
    lines.append("| --- | --- | --- |")
    for dep, display in (("hypothesis", "Hypothesis"), ("pytest_cov", "pytest-cov")):
        if dep in environment.get("missing_deps", []):
            status = "⚠️ WARN"
            hint = DEPENDENCY_HINTS.get(dep, "")
        else:
            status = "✅ PASS"
            hint = "-"
        lines.append(f"| {display} | {status} | {hint} |")
    if environment.get("skipped_tests"):
        lines.append("")
        lines.append("**Skipped tests due to missing dependencies:**")
        for skipped in environment["skipped_tests"]:
            file_name = skipped.get("file", "?")
            missing = skipped.get("missing", "dependency")
            hint = skipped.get("hint", "")
            lines.append(f"- `{file_name}` ⟶ نیازمند {missing}. {hint}")
    lines.append("")
    lines.append("| Result | Severity | ID | Title | Evidence | Hint |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for check in checks:
        if check.result == "pass":
            badge = "✅ PASS"
        elif check.severity == "warning":
            badge = "⚠️ WARN"
        else:
            badge = "❌ FAIL"
        evidence = check.evidence.replace("|", "\\|")
        hint = check.hint.replace("|", "\\|")
        lines.append(
            f"| {badge} | {check.severity} | {check.id} | {check.title} | {evidence} | {hint} |"
        )
    lines.append("")
    lines.append(f"JSON report: `{json_path}`")
    if md_path:
        lines.append(f"Markdown report: `{md_path}`")
    if tests.command:
        command_str = " ".join(tests.command)
    else:
        command_str = "<tests skipped>"
    lines.append(f"Executed command: `{command_str}`")
    if tests.notes:
        lines.append("")
        lines.append("Notes:")
        for note in tests.notes:
            lines.append(f"- {note}")
    return "\n".join(lines)


def build_json_payload(
    checks: list[CheckResult],
    tests: TestResult,
    status: str,
    environment: dict[str, object],
) -> dict:
    """Assemble the JSON document structure."""

    return {
        "status": status,
        "tests": {
            "exit_code": tests.exit_code,
            "passed": tests.passed,
            "failed": tests.failed,
            "errors": tests.errors,
            "duration_s": round(tests.duration_s, 3),
            "coverage_present": tests.coverage_present,
            "executed": tests.executed_tests,
            "skipped": tests.skipped_tests,
            "command": tests.command,
            "notes": tests.notes,
        },
        "environment": environment,
        "checks": [
            {
                "id": check.id,
                "title": check.title,
                "result": check.result,
                "severity": check.severity,
                "evidence": check.evidence,
                "hint": check.hint,
            }
            for check in checks
        ],
    }


def determine_exit_code(
    checks: list[CheckResult],
    tests: TestResult,
    strict: bool,
    missing_deps: list[str],
    strict_missing_deps: bool,
) -> tuple[int, str]:
    """Compute exit code and overall status string."""

    spec_failures = [
        check
        for check in checks
        if check.result == "fail" and (check.severity == "error" or strict)
    ]
    deps_issue = bool(missing_deps) and strict_missing_deps
    tests_failed = tests.exit_code != 0
    spec_problem = bool(spec_failures) or deps_issue
    if tests_failed and spec_problem:
        return 3, "fail"
    if tests_failed:
        return 1, "fail"
    if spec_problem:
        return 2, "fail"
    return 0, "pass"


def ensure_parent(path: Path) -> None:
    """Create parent directories for *path* if missing."""

    path.parent.mkdir(parents=True, exist_ok=True)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for CLI usage."""

    parser = argparse.ArgumentParser(description="Audit Phase-1 compliance")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Path to repository root")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/phase1_audit.json"),
        help="Path to JSON output (directories will be created)",
    )
    parser.add_argument(
        "--md",
        type=Path,
        default=None,
        help="Optional path to write Markdown report (also printed to stdout)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when warning-level findings are present",
    )
    parser.add_argument(
        "--strict-missing-deps",
        action="store_true",
        help="Treat missing optional dependencies as failures",
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    dependencies = detect_dependencies()
    plain_tests, hypothesis_tests, _ = categorize_test_modules(repo)
    skipped_tests: list[dict[str, str]] = []
    tests_to_run = list(plain_tests)
    if dependencies.get("hypothesis", False):
        tests_to_run.extend(hypothesis_tests)
    else:
        for relative in hypothesis_tests:
            skipped_tests.append(
                {
                    "file": relative,
                    "reason": "SKIPPED_DUE_TO_DEPENDENCY",
                    "missing": "hypothesis",
                    "hint": DEPENDENCY_HINTS["hypothesis"],
                }
            )

    context = AuditContext(repo=repo)
    checks = execute_checks(context)
    tests = run_tests(
        repo=repo,
        tests_to_run=tests_to_run,
        coverage_enabled=dependencies.get("pytest_cov", False),
        skipped=skipped_tests,
    )
    downgrade_checks_for_dependency_skips(checks, tests.skipped_tests)

    missing_deps = [name for name, present in dependencies.items() if not present]
    environment = {
        "python": platform.python_version(),
        "missing_deps": missing_deps,
        "coverage_supported": dependencies.get("pytest_cov", False),
        "executed_tests": tests.executed_tests,
        "skipped_tests": tests.skipped_tests,
    }
    if not environment["coverage_supported"]:
        environment["coverage_hint"] = DEPENDENCY_HINTS["pytest_cov"]

    exit_code, status = determine_exit_code(
        checks,
        tests,
        args.strict,
        missing_deps,
        args.strict_missing_deps,
    )

    ensure_parent(args.out)
    json_payload = build_json_payload(checks, tests, status, environment)
    args.out.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown = render_markdown(
        checks,
        tests,
        args.out.resolve(),
        args.md.resolve() if args.md else None,
        environment,
    )
    if args.md:
        ensure_parent(args.md)
        args.md.write_text(markdown, encoding="utf-8")
    print(markdown)
    print()
    print(f"JSON report written to: {args.out.resolve()}")
    if args.md:
        print(f"Markdown report written to: {args.md.resolve()}")
    print(
        "Exit code: "
        f"{exit_code} (strict={args.strict}, strict_missing_deps={args.strict_missing_deps})"
    )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
