# Developer Workflow Cheatsheet

## Deterministic 100/100 Quality Run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
pytest \
  -W error \
  -p pytest_jsonreport \
  --json-report \
  --json-report-file=reports/pytest.json \
  --junitxml=reports/junit.xml \
  tests/plugins/test_plugin_stubs.py \
  tests/retry/test_retry_backoff_metrics.py \
  tests/middleware/test_order_post.py \
  tests/time/test_no_wallclock_repo_guard.py \
  tests/export/test_csv_excel_hygiene.py \
  tests/idem/test_concurrent_posts.py \
  tests/perf/test_exporter_perf.py \
  tests/domain/test_validate_registration.py \
  | tee reports/pytest-summary.txt
python strict_report.py
```

The command enforces warnings-as-errors, produces `reports/pytest.json`, `reports/junit.xml`, and `reports/pytest-summary.txt`, then emits the Strict Scoring v2 report with full evidence coverage.
