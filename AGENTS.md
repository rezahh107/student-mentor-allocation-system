# AGENTS.md — ImportToSabt Project (v5.2 • Performance-First, Debug-First 80/20)

A single, predictable brief for **AI Python Debugging & Performance agents** working on this repository.  
Keep responses **deterministic, efficient, and testable**. Never leak PII. Never guess env/secrets.  
**Default operating mode:** **80% debugging & optimization / 20% minimal code changes (only when unavoidable).**

---

## 1) Project TL;DR

- **Stack:** Python **3.11.9 (pinned)**, FastAPI, PostgreSQL, Redis, SSR (Jinja2 + HTMX).
- **Primary focus:** Performance & Debugging — find and fix bottlenecks, memory leaks, and concurrency issues.
- **Determinism:** All time reads via an **injected Clock**; **IANA tz = Asia/Tehran** (no wall-clock). Tests **freeze/mock** time.
- **Python standards:** PEP 8, type hints (PEP 484/526), readability over cleverness, 3.11 idioms (async/await for I/O, `functools.lru_cache`, `dataclasses` when appropriate).
- **Excel safety:** UTF-8, CRLF, optional BOM, **always-quote** sensitive columns, **formula-guard** (`'` prefix), NFKC, digit folding, unify `ی/ك`.
- **Atomic I/O:** write to `.part` → `fsync` → atomic `os.replace`/rename.
- **Middleware order (MUST):** `RateLimit → Idempotency → Auth` (verified by tests).
- **Performance budgets:** Exporter **p95 < 15s / 100k**, **p99 < 20s**, **Mem < 150MB**; Health **p95 < 200ms**.
- **Observability & minimal security (maintenance-only):** JSON logs with **Correlation-ID**, **no raw PII**; `/metrics` token-guard; downloads via signed-URL. Do **not** add new security features that harm performance.
- **Endpoint reality:** Discover endpoints only from registered **routers & OpenAPI**. Do **not** invent paths.
- **User-visible errors:** **Persian**, deterministic; internals/docs may be English.

---

## 2) Setup & Commands

> Agents must **fail fast on warnings** and assume shared/flaky CI runners (use retries with **deterministic jitter**).

- **Python:** **3.11.9 exactly** (must equal `python --version`).
- **Install:** `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- **Run tests (no plugins; strict):** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --warnings=error`
- **Dev server (adjust entrypoint if needed):** `uvicorn main:app --reload`
- **Lint:** `ruff check .`
- **(Advisory) Security scan:** `bandit -q -r src` (non-blocking; performance has priority).
- **Profiling (recommended):**
  - CPU: `python -m cProfile -o profile.out src/main.py`
  - Memory: use `tracemalloc` and `time.perf_counter` in performance tests

If tests rely on Redis/PostgreSQL, run local services or docker-compose. **Clean Redis/DB/tmp before & after tests**, use **unique namespaces**, and **reset Prometheus CollectorRegistry**. Performance tests should report **p50/p95/p99** and **memory deltas**.

### Windows Smoke & Acceptance (short)
1. Verify Python: `python --version` → `3.11.9`.
2. In PowerShell at repo root:
   ```powershell
   $env:IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS = "true"
   $env:METRICS_TOKEN = "dev-metrics"
   python scripts\hooks\no_src_main_check.py
   ```powershell

3. Run `.\run_application.bat` (entrypoint: `main:app`).
4. Validate:

   * `/openapi.json`, `/docs`, `/redoc` → 200 when PUBLIC_DOCS=1
   * `/metrics` w/o token → 403; with `Authorization: Bearer dev-metrics` → 200

### CI Integration

* Workflow: `.github/workflows/windows-smoke.yml`
* **Strict Scoring v2:** pipeline fails if overall score < 100.
* Tests avoid wall-clock; diagnostics may use monotonic timers only.

> **No-100 Gate:** if any of `skipped`, `xfailed`, or `warnings` > 0, score is **auto-capped below 100** and CI fails.

---

## 3) Absolute Guardrails (performance-first do/do-not)

* ✅ **Prioritize performance:** every change must respect budgets. Fixes causing regressions are unacceptable.
* ✅ **Verify** middleware order `RateLimit → Idempotency → Auth` for **POST** paths.
* ✅ **Inject** `Clock(tz="Asia/Tehran")` everywhere; never call `datetime.now()` directly.
* ✅ **Emit** Prometheus metrics; JSON logs include Correlation-ID; mask/hash identifiers (no raw PII).
* ✅ **Maintain** Excel safety for CSV/XLSX (see §5).
* ✅ **Write** artifacts atomically (`.part → fsync → replace`).
* ✅ **Endpoint reality:** use only OpenAPI/routers. If `/api/exports` doesn’t exist, align to the actual flow (e.g., `/api/exports/csv` or job-based).
* ❌ No wall-clock, no invented endpoints, no state-cleanup skips, no performance regressions.
* ❌ Security changes beyond maintenance-only.

---

## 4) Domain Rules (normalization & validation)

* **Text normalization:** NFKC, unify `ی/ك`, strip zero-width/control, trim.
* **Phone (after folding):** `^09\d{9}$`.
* **Enums:** `reg_center ∈ {0,1,2}`, `reg_status ∈ {0,1,3}` (reject others).
* **Derived:** `StudentType` depends on `SpecialSchoolsRoster(year)`.
* **Year code:** from `AcademicYearProvider` (**never** `now()`).
* **Evidence (Core Models):** `src/models/student.py::Student`

---

## 5) Uploads & Exports (strict)

### Uploads — `ROSTER_V1`

* API: `POST /uploads` (`.csv|.zip|.xlsx` ≤ 50MB), `GET /uploads/{id}`, `POST /uploads/{id}/activate`.
* **Validation:** UTF-8; **CRLF** (CSV); header required; `school_code>0`; digit folding; **formula-guard**; safe ZIP extraction.
* **Atomic store & manifest:** persist under `sha256/<digest>` with `upload_manifest.json`.
* **Activate:** only one active roster per `year` (locking/txn).
* **Performance:** prefer streaming/chunking; avoid loading large files fully into memory.

### Exports — `SABT_V1` (**primary optimization target**)

* Start `POST /exports?format=xlsx|csv` (default: xlsx); status `GET /exports/{id}`.
* **Stable sort:** `(year_code, reg_center, group_code, coalesce(school_code,999999), national_id)` (ensure memory-efficient).
* **Chunking:** default 50,000 rows; XLSX default: **single file, multi-sheet** (tune chunk size).
* **Excel safety:** UTF-8; **CRLF**; optional BOM; **always-quote** sensitive columns; **formula-guard**; strip control chars.
* **Finalize atomically:** write parts → `fsync` → replace; write `export_manifest.json` **after** files.
* **Evidence (Excel Safety):** `src/utils/excel_safety.py::make_excel_safe`
* **Evidence (Export Logic):** `src/services/export.py::export_to_csv`, `src/services/export.py::export_to_xlsx`

---

## 6) Observability & Minimal Security

* **Metrics (examples):** `export_jobs_total`, `export_duration_seconds`, `uploads_total`, `db_query_latency_seconds`, `cache_hit_ratio`.
* **Logs:** structured JSON; include `correlation_id`, operation context, retry counts, **query durations**, **cache hit/miss**; **no raw PII**.
* **Security (maintenance-only):** keep `/metrics` token-guard and signed-URL downloads; default TTL 3600s (change only if required).
* **Evidence (Token Guard):** `src/middleware/auth.py::metrics_token_guard`
* **Evidence (Security Tests):** `tests/security/test_metrics_token_guard.py`

---

## 7) Performance & Reliability (PRIMARY)

* **Budgets:** Exporter **p95 < 15s/100k**, **p99 < 20s**, **Mem < 150MB**; health/readiness **p95 < 200ms**.
* **Measurement:** use `time.perf_counter` (latency), **cProfile** (CPU), **tracemalloc** (memory) in tests.
* **Retries:** exponential backoff + **deterministic** jitter (BLAKE2-seeded). Inject `sleep_fn` in tests (no real `sleep`).
* **Concurrency:** cap job concurrency; apply backpressure; respect pool timeouts; load tests (≥100 concurrent where applicable).
* **Evidence (Retry):** `src/utils/retry.py::retry_with_backoff`
* **Evidence (Redis):** `config/redis.py`

---

## 8) Testing & CI Gates (with performance harness)

* **Warnings = 0** (`--warnings=error`).
* **Freeze/mocks** for TTL/backoff/time; **no sleeps** for timing.
* **State hygiene:** clean **Redis/DB/tmp** pre/post; unique namespaces; **reset CollectorRegistry**.
* **Middleware order test** for POST paths must pass.
* **Performance harness:** tests must assert **p50/p95/p99** and **memory deltas** against budgets.
* **Evidence Map:** each spec item (sections **§1–§15**) must have ≥1 **exact evidence** (`path::symbol` or `tests::name`).
* **Strict Scoring v2** enforced; totals are capped if skips/xfails/warnings exist.
* **Evidence (Fixtures):** `tests/fixtures/state.py::clean_state`, `tests/fixtures/time.py::injected_clock`
* **Evidence (Middleware Test):** `tests/integration/test_middleware.py::test_middleware_order_on_post_endpoints`

> **No-100 Gate:** `skipped + xfailed + warnings > 0` ⇒ auto-cap below 100 with a stated reason.

---

## 9) RBAC, Audit & Retention (maintenance-only)

* RBAC: ADMIN (global) vs MANAGER (center-scoped). Enforce on API/UI.
* Audit (append-only): record `UPLOAD_*`, `EXPORT_*`, `AUTHN_*` with `ts` from injected clock, `actor_role`, `outcome`. **No PII**.
* Retention: monthly archives (CSV/JSON **Excel-safe** + manifest), WORM-style; purge only after valid archive exists.
* **Do not modify** unless a bug originates here.

---

## 10) User-Visible Errors (Persian, deterministic)

* `UPLOAD_VALIDATION_ERROR`: «فایل نامعتبر است؛ ستون school_code الزامی است.»
* `EXPORT_VALIDATION_ERROR`: «درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.»
* `RATE_LIMIT_EXCEEDED`: «محدودیت درخواست؛ لطفاً کمی صبر کنید.»
* `UNAUTHORIZED`: «دسترسی غیرمجاز؛ لطفاً وارد شوید.»

---

## 11) Primary Operational Mode — Debug-First (80/20)

1. **Analyze & profile:** Apply the 5-Layer framework (§13) + cProfile + tracemalloc; **quantify** issues (e.g., p95=22s; +50MB).
2. **Minimal fix:** smallest possible change (algorithmic improvements, batching, async I/O, caching; remove N+1).
3. **Verify:** add/update edge/concurrency/perf tests; budgets must pass.
4. **Report:** output Diagnostic and Quality reports.

**Optional: Code Generation Mode** only when a minimal new feature is strictly required; still honor all budgets and guardrails.

---

## 12) Agent Playbook (debug/perf tasks)

* **Locate bottlenecks:** cProfile/flame graph on exporter and hot paths.
* **Reduce memory:** tracemalloc for leaks/heavy allocs; prefer streaming/chunking over full file loads.
* **Fix flaky tests:** 5-Layer; capture state snapshots; CI vs local diffs; mock external dependencies.
* **Optimize DB access:** remove N+1; add indexes; use prefetch/batching; consider `EXPLAIN ANALYZE`.
* **Endpoint reality fixes:** if tests hit a non-existent path, align them to the **actual** OpenAPI/routers path.

**Quality Assessment Report (Performance-Focused):**

════════ QUALITY ASSESSMENT REPORT ════════
TOTAL: __/100 → Level: [Excellent/Good/Average/Poor]

AGENTS.md Compliance:
├─ Performance budgets met: ✅/❌ — evidence: <tests::perf_test_name>
├─ Clock injection (Asia/Tehran): ✅/❌ — evidence: <path::symbol>
├─ State cleanup (before/after): ✅/❌ — evidence: <path::fixture>
├─ Minimal change applied: ✅/❌ — evidence: [__ lines in diff]
└─ Root cause identified: ✅/❌ — evidence: [Diagnostic Report]

Pytest Summary:
- passed=__, failed=__, xfailed=__, skipped=__, warnings=__

Next Actions:
[ ] (Empty list = eligible for 100/100)


## 13) Debugging & RCA Framework (5 layers)

* **L1 Symptoms:** exception, message, stacktrace, frequency; **quantified performance impact** (e.g., +7s p95).
* **L2 State:** Redis keys/TTLs, DB transactions, middleware order, connection pools.
* **L3 Timing:** per-stage breakdown (`time.perf_counter`), **cProfile** results, I/O wait vs CPU, network vs compute.
* **L4 Environment:** CI vs local diffs, resource limits, dependency versions, timeouts, **tracemalloc snapshots**.
* **L5 Concurrency:** race windows, contention, pool exhaustion, deadlocks.

**Common Anti-Patterns to flag & replace:**

* `datetime.now()` → injected `clock.now()`
* direct file writes → **atomic write** pattern
* random jitter → **deterministic** jitter
* N+1 queries → batching/prefetch
* full-memory file loads → streaming/chunking
* blocking I/O in async context → `asyncio.to_thread()` or proper async libs

**Evidence (Debug Helpers):** `src/utils/debug.py::capture_debug_snapshot`, `tests/fixtures/debug.py::debug_context`, `tests/performance/*`

---

## 14) Definition of Done (performance-first)

* [ ] **Performance budgets met** (export p95/p99/mem) with performance tests; Pytest **Warnings=0**; evidence added.
* [ ] No wall-clock; injected **Asia/Tehran** clock only; tests freeze time.
* [ ] Middleware order test passes; state hygiene and CollectorRegistry reset.
* [ ] The change is the **minimal possible** to solve the problem.
* [ ] 5-Layer Analysis completed and reports generated.

---

## 15) Quick Reference & Decision Tree (perf-centric)

* **Budgets:** Export **p95 < 15s/100k**, **p99 < 20s**, Mem **< 150MB** | Health **p95 < 200ms**.
* **Primary tools:** `cProfile`, `tracemalloc`, `time.perf_counter`, 5-Layer RCA.
* **Security (maintenance-only):** preserve existing guards (`/metrics` token; signed URLs, TTL=3600s); do not extend.
* **Tests:** `clean_state`, `injected_clock` fixtures required | Warnings = 0 | Evidence per §1–§15.
* **Decision:** All tasks start in **Debug-First** mode; Code Generation only if strictly necessary.

```

::contentReference[oaicite:0]{index=0}
```
