pipeline {
  agent any
  options {
    disableConcurrentBuilds()
  }
  environment {
        PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
        PYTHONUTF8 = '1'
        MPLBACKEND = 'Agg'
        QT_QPA_PLATFORM = 'offscreen'
        PYTHONDONTWRITEBYTECODE = '1'
        PYTHONWARNINGS = 'error'
        REDIS_URL = "${env.CI_REDIS_URL ?: 'redis://localhost:6379/0'}"
        STRICT_SCORE_JSON = 'reports/strict_score.json'
        CI_CORRELATION_ID = 'be862f1780d7'
  }
  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }
    stage('Setup') {
      steps {
        sh "PYTHONWARNINGS=default python3 -m scripts.deps.ensure_lock --root . install --attempts 3"
        sh "PYTHONWARNINGS=default python3 -m pip install --no-deps -e ."
      }
    }
    stage('CI Orchestrator Smoke') {
      steps {
        withEnv(['CI_INSTALL_CMD=python -m pip --version', 'CI_TEST_CMD=python -m pytest --version']) {
          sh 'python3 -m ci_orchestrator.main all'
        }
      }
    }
    stage('Test') {
      steps {
        sh '''
export PYTHONWARNINGS=error
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONUTF8=1
export MPLBACKEND=Agg
export QT_QPA_PLATFORM=offscreen
export PYTHONDONTWRITEBYTECODE=1
python3 -m tools.ci_test_orchestrator --json reports/strict_score.json
# Evidence: tests/mw/test_order_with_xlsx.py::test_middleware_order_post_exports_xlsx
# Evidence: tests/time/test_clock_tz.py::test_clock_timezone_is_asia_tehran
# Evidence: tests/hygiene/test_prom_registry_reset.py::test_registry_reset_once
        # Evidence: tests/obs/test_metrics_protected.py::test_metrics_endpoint_is_public
# Evidence: tests/exports/test_excel_safety_ci.py::test_always_quote_and_formula_guard
# Evidence: tests/exports/test_xlsx_finalize.py::test_atomic_finalize_and_manifest
# Evidence: tests/perf/test_health_ready_p95.py::test_readyz_p95_lt_200ms
# Evidence: tests/i18n/test_persian_errors.py::test_deterministic_error_messages
'''
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'reports/strict_score.json', allowEmptyArchive: false
    }
  }
}
