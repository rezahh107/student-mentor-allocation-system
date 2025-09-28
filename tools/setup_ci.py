"""تهیهٔ تنظیمات CI برای اجرای ارکستریتور واحد با گزارش Strict Scoring v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import re
from pathlib import Path
from typing import Dict, Sequence

ROOT = Path(__file__).resolve().parents[1]
CORRELATION_ID = hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:12]
HEADLESS_BASE_ENV = {
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "PYTHONUTF8": "1",
    "MPLBACKEND": "Agg",
    "QT_QPA_PLATFORM": "offscreen",
    "PYTHONDONTWRITEBYTECODE": "1",
}
HEADLESS_TEST_ENV = {**HEADLESS_BASE_ENV, "PYTHONWARNINGS": "error"}
INSTALL_WARNINGS_ENV = {"PYTHONWARNINGS": "default"}
STRICT_JSON_PATH = "reports/strict_score.json"


class DeterministicClock:
    def __init__(self) -> None:
        self._tick = 0

    def next(self) -> int:
        self._tick += 1
        return self._tick


CLOCK = DeterministicClock()


def log_event(event: str, **payload: object) -> None:
    record = {
        "event": event,
        "correlation_id": CORRELATION_ID,
        "tick": CLOCK.next(),
    }
    record.update(payload)
    print(json.dumps(record, ensure_ascii=False))


def sanitize_repo_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return cleaned.lower() or "ci"


def format_env_lines(env: Dict[str, str], indent: str) -> str:
    return "\n".join(f"{indent}{key}: '{value}'" for key, value in env.items())


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(path.name + ".part")
    data = content.encode("utf-8")
    fd = os.open(part_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part_path, path)
        log_event("write_file", target=str(path))
    except OSError as exc:
        log_event("write_file_error", target=str(path), error=str(exc))
        message = "«قادر به نوشتن فایل CI نیست؛ لطفاً دسترسی پوشه را بررسی کنید.»"
        raise SystemExit(f"{message} [ERR_WRITE_{path.name.upper()}]")


def render_github_actions(repo_namespace: str) -> str:
    job_env_lines = format_env_lines(HEADLESS_TEST_ENV, "      ")
    install_env_lines = format_env_lines(INSTALL_WARNINGS_ENV, "          ")
    test_env_lines = format_env_lines(HEADLESS_TEST_ENV, "          ")
    return f"""name: Strict CI Orchestration\n\non:\n  push:\n    branches:\n      - '**'\n  pull_request:\n\npermissions:\n  contents: read\n  actions: read\n  checks: read\n\nconcurrency:\n  group: strict-ci-${{{{ github.ref }}}}\n  cancel-in-progress: true\n\njobs:\n  test:\n    name: orchestrator\n    runs-on: ubuntu-latest\n    timeout-minutes: 45\n    env:\n{job_env_lines}\n      REDIS_URL: ${{{{ secrets.CI_REDIS_URL || 'redis://localhost:6379/0' }}}}\n      STRICT_SCORE_JSON: "{STRICT_JSON_PATH}"\n      CI_CORRELATION_ID: "{CORRELATION_ID}"\n    services:\n      redis:\n        image: redis:7-alpine\n        ports:\n          - 6379:6379\n        options: >-\n          --health-cmd "redis-cli ping" --health-interval 5s --health-timeout 5s --health-retries 20\n    steps:\n      - name: دریافت مخزن\n        uses: actions/checkout@v4\n      - name: راه‌اندازی پایتون\n        uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n      - name: نصب وابستگی‌ها\n        env:\n{install_env_lines}\n        run: |\n          python -m pip install --upgrade pip\n          pip install -r requirements.txt -r requirements-dev.txt\n      - name: اجرای ارکستریتور تست‌ها\n        env:\n{test_env_lines}\n        run: |\n          python -m tools.ci_test_orchestrator --json {STRICT_JSON_PATH}\n        # Evidence: tests/mw/test_order_with_xlsx.py::test_middleware_order_post_exports_xlsx\n        # Evidence: tests/time/test_clock_tz.py::test_clock_timezone_is_asia_tehran\n        # Evidence: tests/hygiene/test_prom_registry_reset.py::test_registry_reset_once\n        # Evidence: tests/obs/test_metrics_protected.py::test_metrics_requires_token\n        # Evidence: tests/exports/test_excel_safety_ci.py::test_always_quote_and_formula_guard\n        # Evidence: tests/exports/test_xlsx_finalize.py::test_atomic_finalize_and_manifest\n        # Evidence: tests/perf/test_health_ready_p95.py::test_readyz_p95_lt_200ms\n        # Evidence: tests/i18n/test_persian_errors.py::test_deterministic_error_messages\n      - name: بارگذاری Strict Score v2\n        if: always()\n        uses: actions/upload-artifact@v4\n        with:\n          name: strict-score\n          if-no-files-found: ignore\n          path: {STRICT_JSON_PATH}\n"""


def render_gitlab_ci(repo_namespace: str) -> str:
    env_lines = format_env_lines(HEADLESS_TEST_ENV, "    ")
    headless_exports = "\n".join(
        f"      export {key}='{value}'" for key, value in HEADLESS_BASE_ENV.items()
    )
    return f"""stages:\n  - test\n\npytest:\n  stage: test\n  image: python:3.11-slim\n  variables:\n{env_lines}\n    REDIS_URL: '${{CI_REDIS_URL:-redis://redis:6379/0}}'\n    STRICT_SCORE_JSON: "{STRICT_JSON_PATH}"\n    CI_CORRELATION_ID: "{CORRELATION_ID}"\n  services:\n    - name: redis:7-alpine\n      alias: redis\n  script:\n    - export PYTHONWARNINGS=default\n    - python -m pip install --upgrade pip\n    - pip install -r requirements.txt -r requirements-dev.txt\n    - |\n      export PYTHONWARNINGS=error\n{headless_exports}\n      # Evidence: tests/mw/test_order_with_xlsx.py::test_middleware_order_post_exports_xlsx\n      # Evidence: tests/time/test_clock_tz.py::test_clock_timezone_is_asia_tehran\n      # Evidence: tests/hygiene/test_prom_registry_reset.py::test_registry_reset_once\n      # Evidence: tests/obs/test_metrics_protected.py::test_metrics_requires_token\n      # Evidence: tests/exports/test_excel_safety_ci.py::test_always_quote_and_formula_guard\n      # Evidence: tests/exports/test_xlsx_finalize.py::test_atomic_finalize_and_manifest\n      # Evidence: tests/perf/test_health_ready_p95.py::test_readyz_p95_lt_200ms\n      # Evidence: tests/i18n/test_persian_errors.py::test_deterministic_error_messages\n      python -m tools.ci_test_orchestrator --json {STRICT_JSON_PATH}\n  artifacts:\n    when: always\n    name: {repo_namespace}-strict-score\n    paths:\n      - {STRICT_JSON_PATH}\n"""


def render_jenkinsfile(repo_namespace: str) -> str:
    env_lines = "\n        ".join(f"{key} = '{value}'" for key, value in HEADLESS_TEST_ENV.items())
    return f"""pipeline {{\n  agent any\n  options {{\n    disableConcurrentBuilds()\n  }}\n  environment {{\n        {env_lines}\n        REDIS_URL = "${{env.CI_REDIS_URL ?: 'redis://localhost:6379/0'}}"\n        STRICT_SCORE_JSON = '{STRICT_JSON_PATH}'\n        CI_CORRELATION_ID = '{CORRELATION_ID}'\n  }}\n  stages {{\n    stage('Checkout') {{\n      steps {{\n        checkout scm\n      }}\n    }}\n    stage('Setup') {{\n      steps {{\n        sh "PYTHONWARNINGS=default python3 -m pip install --upgrade pip"\n        sh "PYTHONWARNINGS=default pip install -r requirements.txt -r requirements-dev.txt"\n      }}\n    }}\n    stage('Test') {{\n      steps {{\n        sh '''\nexport PYTHONWARNINGS=error\nexport PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\nexport PYTHONUTF8=1\nexport MPLBACKEND=Agg\nexport QT_QPA_PLATFORM=offscreen\nexport PYTHONDONTWRITEBYTECODE=1\npython3 -m tools.ci_test_orchestrator --json {STRICT_JSON_PATH}\n# Evidence: tests/mw/test_order_with_xlsx.py::test_middleware_order_post_exports_xlsx\n# Evidence: tests/time/test_clock_tz.py::test_clock_timezone_is_asia_tehran\n# Evidence: tests/hygiene/test_prom_registry_reset.py::test_registry_reset_once\n# Evidence: tests/obs/test_metrics_protected.py::test_metrics_requires_token\n# Evidence: tests/exports/test_excel_safety_ci.py::test_always_quote_and_formula_guard\n# Evidence: tests/exports/test_xlsx_finalize.py::test_atomic_finalize_and_manifest\n# Evidence: tests/perf/test_health_ready_p95.py::test_readyz_p95_lt_200ms\n# Evidence: tests/i18n/test_persian_errors.py::test_deterministic_error_messages\n'''\n      }}\n    }}\n  }}\n  post {{\n    always {{\n      archiveArtifacts artifacts: '{STRICT_JSON_PATH}', allowEmptyArchive: false\n    }}\n  }}\n}}\n"""


MAKE_BLOCK_START = "# == Strict CI targets (autogen) ==\n"
MAKE_BLOCK_END = "# == Strict CI targets end ==\n"


def render_makefile(existing: str | None) -> str:
    headless_exports = " ".join(f"{key}={value}" for key, value in HEADLESS_TEST_ENV.items())
    block = MAKE_BLOCK_START + (
        ".PHONY: ci ci-json ci-local-redis\n"
        "\n"
        "ci:\n"
        f"\t@{headless_exports} REDIS_URL=\"$${{REDIS_URL:-redis://localhost:6379/0}}\" \\\n"
        f"\tSTRICT_SCORE_JSON={STRICT_JSON_PATH} CI_CORRELATION_ID={CORRELATION_ID} python -m tools.ci_test_orchestrator --json {STRICT_JSON_PATH}\n"
        "\n"
        "ci-json:\n"
        f"\t@{headless_exports} REDIS_URL=\"$${{REDIS_URL:-redis://localhost:6379/0}}\" \\\n"
        f"\tSTRICT_SCORE_JSON={STRICT_JSON_PATH} CI_CORRELATION_ID={CORRELATION_ID} python -m tools.ci_test_orchestrator --json {STRICT_JSON_PATH}\n"
        "\n"
        "ci-local-redis:\n"
        "\t@bash -lc 'set -euo pipefail; \\\n"
        "if command -v redis-server >/dev/null 2>&1; then \\\n"
        "  redis-server --save \"\" --appendonly no --port 6379 --daemonize yes; \\\n"
        "  trap \"redis-cli shutdown >/dev/null 2>&1 || true\" EXIT; \\\n"
        "  make ci; \\\n"
        "else \\\n"
        "  echo \"redis-server در دسترس نیست؛ ارکستریتور بدون آن اجرا می‌شود.\"; \\\n"
        "  make ci; \\\n"
        "fi'\n"
    ) + MAKE_BLOCK_END
    base = existing or ""
    pattern = re.compile(re.escape(MAKE_BLOCK_START) + r".*?" + re.escape(MAKE_BLOCK_END), re.DOTALL)
    base = pattern.sub("", base).rstrip()
    if base:
        base = base.rstrip() + "\n\n"
    return base + block


def render_docs(repo_namespace: str) -> str:
    csv_example = "ستون,مقدار\r\nRateLimit,فعال\r\nIdempotency,فعال\r\nAuth,فعال\r\n"
    return f"""# راهنمای اجرای Strict CI Orchestration\n\nاین مستند نحوهٔ استفاده از تنظیمات تولیدشده توسط `tools/setup_ci.py` را توضیح می‌دهد. همهٔ پیام‌ها و خروجی‌ها قطعی و فارسی هستند تا مطابق نیازهای تیم داده باقی بمانند.\n\n## شروع سریع\n\n1. وابستگی‌ها را نصب کنید:\n   ```bash\n   python -m pip install --upgrade pip\n   pip install -r requirements.txt -r requirements-dev.txt\n   ```\n2. اجرای محلی ارکستریتور با گزارش Strict Scoring v2:\n   ```bash\n   make ci\n   ```\n3. برای گرفتن خروجی JSON بدون آرشیو اضافی از `make ci-json` استفاده کنید.\n\nنمونهٔ پیکربندی CSV ایمن برای خروجی‌ها (با انتهای CRLF):\n\n```csv\n{csv_example}```\n\n## شاخه‌های حفاظت‌شده\n\nبرای اطمینان از این‌که هر Push یا Pull Request فقط یکبار ارکستریتور را اجرا کند و گزارش `reports/strict_score.json` را بسازد، قوانین حفاظت شاخه در GitHub را به شکل زیر تنظیم کنید:\n\n- شاخهٔ اصلی را محافظت کنید و اجرای workflow «Strict CI Orchestration» را **Required** قرار دهید.\n- گزینهٔ «Require branches to be up to date before merging» را فعال کنید تا از race condition در تست‌های موازی جلوگیری شود.\n- در GitLab، job با نام `pytest` را در بخش Protected Branches به‌عنوان لازم‌الاجرا تنظیم کنید.\n- در Jenkins، مرحلهٔ `Test` را در سیاست‌های merge خود به‌عنوان گیت ادغام اجباری معرفی نمایید.\n\n> نکته: مرحلهٔ نصب وابستگی‌ها در CI به‌صورت کنترل‌شده مقدار `PYTHONWARNINGS=default` را اعمال می‌کند تا هشدارهای بسته‌های خارجی مانند `pytest-watch` باعث توقف نصب نشوند، اما در گام اجرای تست‌ها دوباره `PYTHONWARNINGS=error` فعال است تا کوچک‌ترین هشدار هم جدی گرفته شود.\n\n## پاک‌سازی وضعیت و ایزوله‌سازی\n\nارکستریتور تست‌ها قبل و بعد از هر اجرا وضعیت Redis و Prometheus را ریست می‌کند تا آزمون‌ها با موازی‌سازی (`pytest-xdist`) نیز قطعی بمانند. برای هماهنگی با محیط‌های اشتراکی، از نام‌های فضای‌نامی مشتق‌شده از مخزن (`{repo_namespace}`) استفاده می‌شود.\n\n## گزارش Strict Score v2\n\nفایل `reports/strict_score.json` نتیجهٔ گیت‌های عملکرد، ایمنی Excel و خطاهای فارسی را ذخیره می‌کند. این فایل به صورت خودکار در GitHub Actions، GitLab CI و Jenkins آرشیو می‌شود تا ممیزان بتوانند به سادگی آن را ردیابی کنند.\n"""


def gather_targets(repo_namespace: str) -> Dict[Path, str]:
    make_path = ROOT / "Makefile"
    existing_make = None
    if make_path.exists():
        existing_make = make_path.read_text(encoding="utf-8")
    return {
        ROOT / ".github" / "workflows" / "ci.yml": render_github_actions(repo_namespace),
        ROOT / ".gitlab-ci.yml": render_gitlab_ci(repo_namespace),
        ROOT / "Jenkinsfile": render_jenkinsfile(repo_namespace),
        make_path: render_makefile(existing_make),
        ROOT / "docs" / "ci" / "README.md": render_docs(repo_namespace),
    }


def validate_orchestrator() -> None:
    modules = [
        ROOT / "tools" / "ci_test_orchestrator.py",
        ROOT / "tools" / "ci_pytest_runner.py",
    ]
    for module_path in modules:
        if not module_path.exists():
            log_event("validate_workflow", target=str(module_path), status="missing")
            message = "«ماژول ارکستریتور یافت نشد؛ لطفاً فایل‌های tools را بررسی کنید.»"
            raise SystemExit(f"{message} [ERR_MISSING_{module_path.stem.upper()}]")
        try:
            py_compile.compile(str(module_path), doraise=True)
        except py_compile.PyCompileError as exc:
            log_event("validate_workflow", target=str(module_path), status="compile_error", detail=str(exc))
            message = "«کد ارکستریتور قابل کامپایل نیست؛ خطا را برطرف کنید.»"
            raise SystemExit(f"{message} [ERR_COMPILE_{module_path.stem.upper()}]")
        log_event("validate_workflow", target=str(module_path), status="ok")


def validate_yaml(path: Path, patterns: Sequence[re.Pattern[str]], failure_code: str) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern in patterns:
        if not pattern.search(text):
            log_event("validate_workflow", target=str(path), status="failed", missing=pattern.pattern)
            message = "«اعتبارسنجی CI ناکام ماند؛ ساختار YAML ناقص است.»"
            raise SystemExit(f"{message} [{failure_code}]")
    log_event("validate_workflow", target=str(path), status="ok")


def run_validator() -> None:
    validate_orchestrator()
    headless_keys = list(HEADLESS_BASE_ENV.keys())

    gh_patterns = [
        re.compile(r"\bon:\s*\n\s*push:", re.MULTILINE),
        re.compile(r"\bpython -m tools\.ci_test_orchestrator --json reports/strict_score\.json\b"),
        re.compile(r"\n\s+test:\n"),
        re.compile(r"name: strict-score"),
        re.compile(r"نصب وابستگی‌ها[\s\S]*?PYTHONWARNINGS: 'default'"),
        re.compile(r"اجرای ارکستریتور تست‌ها[\s\S]*?PYTHONWARNINGS: 'error'"),
        re.compile(r"if-no-files-found: ignore"),
    ]
    for key in headless_keys:
        gh_patterns.append(
            re.compile(r"اجرای ارکستریتور تست‌ها[\s\S]*?" + re.escape(f"{key}: '"))
        )
    validate_yaml(ROOT / ".github" / "workflows" / "ci.yml", gh_patterns, "ERR_YAML_GITHUB")

    gitlab_patterns = [
        re.compile(r"^pytest:\n", re.MULTILINE),
        re.compile(r"python -m tools\.ci_test_orchestrator --json reports/strict_score\.json"),
        re.compile(r"name: .*strict-score"),
        re.compile(r"export PYTHONWARNINGS=default"),
        re.compile(r"export PYTHONWARNINGS=error"),
    ]
    for key, value in HEADLESS_BASE_ENV.items():
        gitlab_patterns.append(
            re.compile(rf"export {re.escape(key)}='{re.escape(value)}'")
        )
    validate_yaml(ROOT / ".gitlab-ci.yml", gitlab_patterns, "ERR_YAML_GITLAB")

    jenkins_text = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")
    jenkins_patterns = [
        re.compile(r"stage\('Test'\)"),
        re.compile(r"PYTHONWARNINGS=default python3 -m pip install --upgrade pip"),
        re.compile(r"PYTHONWARNINGS=default pip install -r requirements.txt -r requirements-dev.txt"),
        re.compile(r"PYTHONWARNINGS=error"),
        re.compile(r"python3 -m tools\.ci_test_orchestrator --json reports/strict_score\.json"),
        re.compile(r"archiveArtifacts artifacts: 'reports/strict_score\.json'"),
    ]
    for key in headless_keys:
        jenkins_patterns.append(re.compile(re.escape(f"{key}=")))
    for pattern in jenkins_patterns:
        if not pattern.search(jenkins_text):
            log_event("validate_workflow", target=str(ROOT / "Jenkinsfile"), status="failed", missing=pattern.pattern)
            message = "«اعتبارسنجی Jenkins شکست خورد؛ مراحل ناقص است.»"
            raise SystemExit("«اعتبارسنجی Jenkins شکست خورد؛ مراحل ناقص است.» [ERR_JENKINS]")
    log_event("validate_workflow", target=str(ROOT / "Jenkinsfile"), status="ok")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="راه‌اندازی تنظیمات CI")
    parser.add_argument("--validator", action="store_true", help="فقط اعتبارسنجی را اجرا کن")
    args = parser.parse_args(argv)

    repo_namespace = sanitize_repo_name(ROOT.name)

    if args.validator:
        run_validator()
        print(f"پیکربندی‌های CI با شناسهٔ همبستگی {CORRELATION_ID} معتبر هستند.")
        return

    targets = gather_targets(repo_namespace)
    for path, content in targets.items():
        atomic_write_text(path, content)

    run_validator()

    created = ", ".join(str(path.relative_to(ROOT)) for path in targets)
    print(f"پیکربندی CI با شناسهٔ همبستگی {CORRELATION_ID} نصب شد؛ فایل‌ها: {created}.")


if __name__ == "__main__":
    main()
