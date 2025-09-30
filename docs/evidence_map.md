# ImportToSabt Evidence Map

| Spec Reference | Implementation Evidence |
| -------------- | ----------------------- |
| AGENTS.md::3 Absolute Guardrails | src/phase6_import_to_sabt/api.py::create_export_api |
| AGENTS.md::3 Absolute Guardrails (Clock) | src/phase6_import_to_sabt/job_runner.py::ExportJobRunner.__init__ |
| AGENTS.md::5 Uploads & Exports | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter.run |
| AGENTS.md::5 Uploads & Exports (Excel Safety) | tests/export/test_csv_golden.py::test_csv_golden_quotes_and_formula_guard |
| AGENTS.md::5 Uploads & Exports (Stable Sort) | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter._sort_rows |
| AGENTS.md::5 Uploads & Exports (Large streaming) | tests/export/test_streaming_large.py::test_streaming_memory_bound |
| AGENTS.md::5 Uploads & Exports (Manifests) | tests/exports/test_manifest.py::test_atomic_manifest_after_files |
| AGENTS.md::5 Uploads & Exports (Atomic I/O) | src/phase6_import_to_sabt/exporter_service.py::atomic_writer |
| AGENTS.md::6 Observability & Security | tests/security/test_metrics_and_downloads.py::test_token_and_signed_url |
| AGENTS.md::6 Observability & Security (PII masking) | tests/logging/test_json_logs.py::test_masking_and_correlation_id |
| AGENTS.md::7 Performance & Reliability | tests/perf/test_exporter_100k.py::test_p95_latency_and_memory_budget |
| AGENTS.md::7 Performance & Reliability (Retry) | tests/retry/test_retry_backoff.py::test_retry_jitter_and_metrics_without_sleep |
| AGENTS.md::8 Testing & CI Gates (State hygiene) | tests/fixtures/state.py::cleanup_fixtures |
| AGENTS.md::3 Absolute Guardrails (Middleware Order) | tests/mw/test_order_uploads.py::test_rate_then_idem_then_auth |
| AGENTS.md::3 Absolute Guardrails (Persian errors) | tests/i18n/test_persian_errors.py::test_error_messages_deterministic |
| AGENTS.md::4 Domain Rules (Year & Counter) | tests/export/test_crosschecks.py::test_counter_prefix_and_regex |
| AGENTS.md::4 Domain Rules (StudentType derivation) | src/phase6_import_to_sabt/exporter_service.py::ImportToSabtExporter._normalize_row |
| AGENTS.md::4 Domain Rules (Snapshot/Delta) | tests/exports/test_delta_window.py::test_delta_no_gap_overlap |
| AGENTS.md::9 RBAC, Audit & Retention | src/phase6_import_to_sabt/security/rbac.py::TokenRegistry.authenticate |
| docs/ci_performance.md::Export Budgets | tests/perf/test_exporter_100k.py::test_p95_latency_and_memory_budget |
| docs/ops_metrics_map.md::Prometheus Metrics | src/phase6_import_to_sabt/metrics.py::ExporterMetrics |
| docs/api-hardening.md::احراز هویت و کنترل دسترسی | src/phase6_import_to_sabt/security/rbac.py::TokenRegistry.authenticate |
| Spec::Edge Cases (null/zero/None) | tests/export/test_edge_cases.py::test_handles_none_and_zero |
| Spec::Edge Cases (mixed digits & long text) | tests/export/test_edge_cases.py::test_mixed_digits_and_long_names |
