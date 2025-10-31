# ImportToSabt Evidence Map

> ⚠️ **هشدار بیلد لوکال:** رفرنس‌های مربوط به RateLimit، Auth و RBAC به نسخهٔ تولید اشاره دارند. در توزیع فعلی این لایه‌ها حذف شده‌اند و باید پیش از استقرار دوباره ادغام شوند.

| Spec Reference | Implementation Evidence |
| -------------- | ----------------------- |
| AGENTS.md::3 Absolute Guardrails | src/phase6_import_to_sabt/api.py::create_export_api |
| AGENTS.md::3 Absolute Guardrails (Clock) | src/phase6_import_to_sabt/job_runner.py::ExportJobRunner.__init__ |
| AGENTS.md::5 Uploads & Exports | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter.run |
| AGENTS.md::5 Uploads & Exports (Excel Safety) | tests/export/test_csv_golden.py::test_csv_golden_quotes_and_formula_guard |
| AGENTS.md::5 Uploads & Exports (CSV BOM/CRLF) | tests/exports/test_csv_bom_crlf.py::test_bom_and_crlf_when_flag_true |
| AGENTS.md::5 Uploads & Exports (XLSX Sensitive-as-Text) | tests/exports/test_xlsx_safety.py::test_sensitive_as_text_and_formula_guard |
| AGENTS.md::5 Uploads & Exports (Stable Sort) | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter._sort_rows |
| AGENTS.md::5 Uploads & Exports (Large streaming) | tests/export/test_streaming_large.py::test_streaming_memory_bound |
| AGENTS.md::5 Uploads & Exports (XLSX streaming writer) | src/services/export.py::export_to_xlsx |
| AGENTS.md::5 Uploads & Exports (Manifests) | tests/exports/test_manifest.py::test_atomic_manifest_after_files |
| AGENTS.md::5 Uploads & Exports (Atomic I/O) | src/phase6_import_to_sabt/exporter_service.py::atomic_writer |
| AGENTS.md::6 Observability & Security | tests/security/test_metrics_and_downloads.py::test_token_and_signed_url |
| AGENTS.md::6 Observability & Security (PII masking) | tests/logging/test_json_logs_pii_scan.py::test_no_pii_in_logs |
| AGENTS.md::6 Observability & Security (/metrics token) | tests/security/test_metrics_token_guard.py::test_metrics_endpoint_is_public |
| AGENTS.md::7 Performance & Reliability | tests/performance/test_export_budget.py::test_export_xlsx_100k_budget |
| AGENTS.md::7 Performance & Reliability (Retry) | tests/retry/test_retry_backoff.py::test_retry_jitter_and_metrics_without_sleep |
| AGENTS.md::7 Performance & Reliability (Exporter retry integration) | tests/exports/test_job_runner_retry_metrics.py::test_export_job_runner_retry_deterministic_backoff |
| AGENTS.md::7 Performance & Reliability (Retry exhaustion metrics) | tests/exports/test_job_runner_retry_metrics.py::test_export_job_runner_retry_exhaustion_records_failure_metrics |
| AGENTS.md::8 Testing & CI Gates (State hygiene) | tests/fixtures/state.py::cleanup_fixtures |
| AGENTS.md::8 Testing & CI Gates (CollectorRegistry reset) | tests/conftest.py::metrics_registry_guard |
| AGENTS.md::8 Testing & CI Gates (Redis namespace guard) | tests/conftest.py::redis_state_guard |
| AGENTS.md::8 Testing & CI Gates (Strict Scoring Parser) | scripts/ci_pytest_summary_parser.py::main |
| AGENTS.md::8 Testing & CI Gates (Strict Scoring Parser Test) | tests/ci/test_ci_pytest_summary_parser.py::test_strict_scoring_v2_all_axes_and_caps |
| AGENTS.md::8 Testing & CI Gates (Export retry hygiene) | tests/exports/test_job_runner_retry_metrics.py::test_export_job_runner_retry_exhaustion_records_failure_metrics |
| AGENTS.md::3 Absolute Guardrails (Middleware Order) | tests/mw/test_order_uploads.py::test_rate_then_idem_then_auth |
| AGENTS.md::3 Absolute Guardrails (Middleware Order POST) | tests/mw/test_order_post.py::test_middleware_order_post_exports_xlsx |
| AGENTS.md::3 Absolute Guardrails (Middleware Order GET) | tests/mw/test_order_get.py::test_middleware_order_get_paths |
| AGENTS.md::3 Absolute Guardrails (RateLimit→Idempotency→Auth) | tests/mw/test_order_clocked.py::test_post_chain_order |
| AGENTS.md::3 Absolute Guardrails (Diagnostics chain proof) | tests/mw/test_middleware_diagnostics_chain.py::test_middleware_chain_recorded_rate_limit_idem_auth |
| AGENTS.md::3 Absolute Guardrails (Idempotency concurrency) | tests/idem/test_concurrent_posts.py::test_only_one_succeeds |
| AGENTS.md::3 Absolute Guardrails (Rate limit Persian errors) | tests/ratelimit/test_limits.py::test_exceed_limit_persian_error |
| AGENTS.md::3 Absolute Guardrails (Persian errors) | tests/i18n/test_persian_errors.py::test_export_validation_error_message_exact |
| AGENTS.md::3 Absolute Guardrails (Idempotency TTL) | tests/idem/test_idem_ttl_24h.py::test_ttl_window |
| AGENTS.md::4 Domain Rules (Year & Counter) | tests/export/test_crosschecks.py::test_counter_prefix_and_regex |
| AGENTS.md::4 Domain Rules (StudentType derivation) | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter._normalize_row |
| AGENTS.md::4 Domain Rules (Snapshot/Delta) | tests/exports/test_delta_window.py::test_delta_no_gap_overlap |
| AGENTS.md::8 Testing & CI Gates (State hygiene verification) | tests/ci/test_state_hygiene.py::test_cleanup_and_registry_reset |
| AGENTS.md::5 Uploads & Exports (Manifest clock) | tests/exports/test_manifest_ts_tehran.py::test_export_manifest_uses_injected_tehran_clock |
| AGENTS.md::6 Observability & Security (Retry metrics) | tests/obs/test_metrics_mw.py::test_retry_exhaustion_metrics_present |
| AGENTS.md::6 Observability & Security (Histogram buckets) | tests/obs/test_retry_histogram.py::test_rate_limit_and_idem_retry_buckets_present |
| AGENTS.md::9 RBAC, Audit & Retention | src/phase6_import_to_sabt/security/rbac.py::TokenRegistry.authenticate |
| docs/ci_performance.md::Export Budgets | tests/performance/test_export_budget.py::test_export_xlsx_100k_budget |
| docs/ci_performance.md::Budget validation script | tests/performance/validate_budgets.py::main |
| docs/ops_metrics_map.md::Prometheus Metrics | src/phase6_import_to_sabt/metrics.py::ExporterMetrics |
| docs/api-hardening.md::احراز هویت و کنترل دسترسی | src/phase6_import_to_sabt/security/rbac.py::TokenRegistry.authenticate |
| Spec::Edge Cases (null/zero/None) | tests/export/test_edge_cases.py::test_handles_none_and_zero |
| Spec::Edge Cases (mixed digits & long text) | tests/export/test_edge_cases.py::test_mixed_digits_and_long_names |
