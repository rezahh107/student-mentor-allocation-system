# CI Performance & Regression

- Run performance tests on a nightly schedule or pre-release pipeline.
- Use markers to skip heavy tests on PRs: `-m "not slow and not stress and not concurrent and not resources"`.
- Nightly job runs:
  - `pytest -m slow tests/performance/test_load.py`
  - `pytest -m stress tests/performance/test_stress.py`
  - `pytest -m concurrent tests/performance/test_concurrency.py`
  - `pytest -m resources tests/performance/test_resources.py`
- Publish metrics via `tests/performance/benchmarks/performance_report.py` and archive artifacts.
- Guardrail regression check: `tests/performance/benchmarks/regression_tests.py` compares against `baseline_metrics.json`.
