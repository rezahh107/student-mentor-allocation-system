.PHONY: test-quick test-standard test-deep test-security test-full dashboard security-dashboard \
            ci-checks fault-tests static-checks post-migration-checks validate-artifacts gui-smoke \
            security-fix security-scan security test test-coverage test-coverage-summary test-legacy \
            automation-audit pii-scan pytest-json fix-config install-dev quality ci-local help

PYTHON ?= python3
PROJECT_ROOT := $(CURDIR)
BANDIT_FAIL_LEVEL ?= MEDIUM
LEGACY_TEST_PATTERN ?= tests/legacy/test_*.py
PYTEST_ARGS ?=
LEGACY_TARGETS ?=
COV_MIN ?= 95
export COV_MIN

# Legacy targets retained for compatibility with existing tooling

help: ## نمایش راهنما
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

fix-config: ## اصلاح پیکربندی pytest
	@echo "🔧 Fixing pytest configuration..."
	@$(PYTHON) scripts/fix_pytest_config.py

install-dev: ## نصب وابستگی‌های توسعه
	@echo "📦 Installing development dependencies..."
	@$(PYTHON) -m pip install --upgrade pip wheel
	@$(PYTHON) -m pip install "pytest>=8.0.0,<9.0.0" "pytest-asyncio>=0.23.0,<0.25.0"
	@$(PYTHON) -m pip install -e .[dev] 2>/dev/null || $(PYTHON) -m pip install -e . || $(PYTHON) -m pip install -r requirements.txt

quality: fix-config ## اجرای بررسی‌های کیفی
	@echo "🧹 Running quality checks..."
	@ruff check . || true
	@mypy . || true
	@pydocstyle . || true

test: fix-config ## اجرای تست‌ها
	@echo "🧪 Running tests..."
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest --verbose --tb=short

ci-local: fix-config install-dev quality test ## اجرای کامل CI در محیط محلی
	@echo "✅ Local CI completed!"

static-checks: quality

ci-checks: ci-local

test-quick:
	$(PYTHON) -m scripts.adaptive_testing --mode=quick

test-standard:
	$(PYTHON) -m scripts.adaptive_testing --mode=standard

test-deep:
	$(PYTHON) -m scripts.adaptive_testing --mode=deep

test-security:
	$(PYTHON) -m scripts.adaptive_testing --mode=security

test-full:
	$(PYTHON) -m scripts.adaptive_testing --mode=full

dashboard:
	$(PYTHON) -m streamlit run scripts/dashboard.py

security-dashboard:
	$(PYTHON) -m streamlit run scripts/security_dashboard.py

# Phase 2 counter service hardening gates

ci-checks:
	PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m scripts.ci_no_pii_scan
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest \
            -p pytest_cov \
            --cov=src.phase2_counter_service \
	            --cov-report=term-missing \
	            --cov-fail-under=$(COV_MIN) \
	            -q tests/phase2_counter_service
	    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m mypy --strict --explicit-package-bases --follow-imports=skip --namespace-packages src/phase2_counter_service scripts/post_migration_checks.py scripts/validate_artifacts.py
	    $(PYTHON) -m bandit -r src/phase2_counter_service
	    $(PYTHON) -m scripts.post_migration_checks
	$(PYTHON) -m scripts.validate_artifacts

fault-tests:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest tests/phase2_counter_service/test_faults.py -q

static-checks:
	PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m scripts.ci_no_pii_scan
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest \
                tests/phase2_counter_service/test_excel_safe.py \
                tests/phase2_counter_service/test_cli.py \
		tests/phase2_counter_service/test_operator_panel_logging.py \
		tests/security/test_bandit_gate.py -q
	
	if [ "$$UI_MINIMAL" != "1" ]; then \
		$(MAKE) gui-smoke; \
	else \
		echo "UI_MINIMAL=1 → حذف کاندید CI برای GUI تست‌های"; \
	fi
	
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m mypy --strict --explicit-package-bases --follow-imports=skip --namespace-packages src/phase2_counter_service scripts/post_migration_checks.py scripts/validate_artifacts.py
	$(MAKE) security-scan

	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest tests/phase2_counter_service/test_no_unused_ignores.py -q

gui-smoke:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest tests/phase2_counter_service/test_gui_smoke.py -q

security-fix:
	PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m scripts.bandit_fixer

post-migration-checks:
	$(PYTHON) -m scripts.post_migration_checks

validate-artifacts:
	$(PYTHON) -m scripts.validate_artifacts

security-scan:
        PYTHONPATH=$(PROJECT_ROOT) BANDIT_FAIL_LEVEL=$(BANDIT_FAIL_LEVEL) $(PYTHON) -m scripts.run_bandit_gate

security: security-scan

pii-scan:
        PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m scripts.ci_no_pii_scan

automation-audit:
	PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m automation_audit.cli --csv

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q

test-coverage:
	    PYTHONPATH=$(PROJECT_ROOT) LEGACY_TEST_PATTERN="$(LEGACY_TEST_PATTERN)" \
	    $(PYTHON) -m scripts.coverage_gate $(if $(LEGACY_TARGETS),$(LEGACY_TARGETS),) --pytest-args "$(PYTEST_ARGS)"

test-coverage-summary:
	    PYTHONPATH=$(PROJECT_ROOT) LEGACY_TEST_PATTERN="$(LEGACY_TEST_PATTERN)" \
	    $(PYTHON) -m scripts.coverage_gate $(if $(LEGACY_TARGETS),$(LEGACY_TARGETS),) --pytest-args "$(PYTEST_ARGS)" --summary

test-legacy:
	    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q tests/legacy -k "not gui" && echo "✅ Legacy tests passed"

# == Strict CI targets (autogen) ==
.PHONY: ci ci-json ci-local-redis

ci:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONUTF8=1 MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error REDIS_URL="$${REDIS_URL:-redis://localhost:6379/0}" \
	STRICT_SCORE_JSON=reports/strict_score.json CI_CORRELATION_ID=be862f1780d7 python -m tools.ci_test_orchestrator --json reports/strict_score.json

ci-json:
	@PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONUTF8=1 MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error REDIS_URL="$${REDIS_URL:-redis://localhost:6379/0}" \
	STRICT_SCORE_JSON=reports/strict_score.json CI_CORRELATION_ID=be862f1780d7 python -m tools.ci_test_orchestrator --json reports/strict_score.json

ci-local-redis:
	@bash -lc 'set -euo pipefail; \
if command -v redis-server >/dev/null 2>&1; then \
	redis-server --save "" --appendonly no --port 6379 --daemonize yes; \
	trap "redis-cli shutdown >/dev/null 2>&1 || true" EXIT; \
	make ci; \
else \
	echo "redis-server در دسترس نیست؛ ارکستریتور بدون آن اجرا می‌شود."; \
	make ci; \
fi'
# == Strict CI targets end ==
pytest-json:
        PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=$(PROJECT_ROOT) $(PYTHON) -m scripts.pytest_json_gate $(PYTEST_ARGS)

