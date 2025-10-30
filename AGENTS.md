# AGENTS.md — ImportToSabt Project (v5.2 • Performance‑First, Debug‑First 80/20)

> **This file is the single source of truth for all AI debugging/performance agents.**
> If any prompt or tool references another version (v5.1 or older), **treat that prompt as stale and abort**.

**Default operating mode:** **80% debugging & optimization / 20% minimal code changes (only when unavoidable).**
Keep responses **deterministic, efficient, and testable**. Never leak PII. Never guess env/secrets.

---

## 0) Reality Map (MANDATORY pre‑step)

Before any analysis or patch:

1. Read this file; record **AGENTS version** (`v5.2`).
2. Enumerate **entrypoints** (e.g., `main:app`) and **routers**; fetch `app.openapi()` paths.
3. Print the **middleware order graph** for **POST** paths.
4. Capture environment snapshot: Python version, OS, important env vars (redacted), service reachability (DB/Redis).

**Abort** if AGENTS version mismatch or OpenAPI cannot be loaded.

---

## 1) Project TL;DR

* **Stack:** Python **3.11.9 (CI pinned)**, FastAPI, PostgreSQL, Redis, SSR (Jinja2 + HTMX).
* **Primary focus:** Performance & Debugging — find/fix bottlenecks, memory leaks, and concurrency issues.
* **Determinism:** All time reads via an **injected Clock**; **IANA tz = Asia/Tehran** (no wall‑clock). Tests **freeze/mock** time.
* **Python standards:** PEP 8, type hints (PEP 484/526), readability over cleverness, 3.11 idioms (async/await for I/O, `functools.lru_cache`, `dataclasses` where appropriate).
* **Excel safety:** UTF‑8, CRLF, optional BOM, **always‑quote** sensitive columns, **formula‑guard** (`'` prefix), NFKC, digit folding, unify `ی/ك`.
* **Atomic I/O:** write to `.part` → `fsync` → atomic `os.replace`/rename.
* **Middleware order (MUST on POST):** `RateLimit → Idempotency → Auth` (verified by tests).
* **Performance budgets:** Export **p95 < 15s / 100k**, **p99 < 20s**, **Mem < 150MB**; Health **p95 < 200ms**.
* **Observability & minimal security:** JSON logs with **Correlation‑ID**, **no raw PII**; `/metrics` token‑guard; signed‑URL downloads.
* **Endpoint reality:** Discover only from registered **routers & OpenAPI**. **Never invent paths.**
* **User‑visible errors:** **Persian**, deterministic; internals/docs may be English.

---

## 2) Setup & Commands

> Agents **fail fast on warnings** and assume shared/flaky CI runners (use retries with **deterministic jitter**).

* **Python policy:**

  * **CI/Containers:** **exact 3.11.9** (must equal `python --version`).
  * **Local dev:** **3.11.x** accepted; warn if minor > 9.
* **Install:** `python -m venv .venv && source .venv/bin/activate && pip install -e .`
* **Run tests (no plugins; strict):** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --warnings=error`
* **Dev server (adjust entrypoint if needed):** `uvicorn main:app --reload`
* **Lint:** `ruff check .`
* **(Advisory) Security scan:** `bandit -q -r src` (non‑blocking; performance has priority).
* **Profiling:** `cProfile`, `tracemalloc`, `time.perf_counter` in tests.

If tests rely on Redis/PostgreSQL, run services locally or via docker‑compose. **Clean Redis/DB/tmp before & after tests**, use **unique namespaces**, and **reset Prometheus CollectorRegistry**. Performance tests must report **p50/p95/p99** and **memory deltas**.

### Windows Smoke & Acceptance (short)

1. Verify Python: `python --version` → `3.11.9` in CI (3.11.x local).
2. Minimal env (example):

```powershell
$env:IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS = "true"
$env:METRICS_TOKEN = "dev-metrics"
python scripts\hooks\no_src_main_check.py
```

3. Run `./run_application.bat` (entrypoint: `main:app`).
4. Validate: `/openapi.json`, `/docs`, `/redoc` (when PUBLIC_DOCS=true); `/metrics` → 403 w/o token, 200 with token.

---

## 3) Absolute Guardrails (performance‑first do/do‑not)

**Do:**

* **Prioritize performance**; fixes cannot regress budgets.
* **Verify** middleware order `RateLimit → Idempotency → Auth` for **POST** paths.
* **Inject** `Clock(tz="Asia/Tehran")`; **no `datetime.now()`/`time.time()` in logic**.
* **Emit** Prometheus metrics; JSON logs include Correlation‑ID; mask/hash identifiers (**no raw PII**).
* **Maintain** Excel safety for CSV/XLSX.
* **Write** artifacts atomically (`.part → fsync → replace`).
* **Endpoint reality:** use only OpenAPI/routers.

**Do‑not:**

* Use wall‑clock time; invent endpoints; skip state cleanup; introduce performance regressions; add new security beyond maintenance.

---

## 4) Domain Rules (normalization & validation)

* **Text normalization:** NFKC, unify `ی/ك`, strip zero‑width/control, trim.
* **Phone (after folding):** `^09\d{9}$`.
* **Enums:** `reg_center ∈ {0,1,2}`, `reg_status ∈ {0,1,3}` (reject others).
* **Derived:** `StudentType` depends on `SpecialSchoolsRoster(year)`.
* **Year code:** from `AcademicYearProvider` (**never** `now()`). Provide a golden test for the current academic year prefix.
* **Evidence (Core Models):** `src/models/student.py::Student` (or actual path in repo).

---

## 5) Uploads & Exports (strict)

### Uploads — `ROSTER_V1`

* API: `POST /uploads` (`.csv|.zip|.xlsx` ≤ 50MB), `GET /uploads/{id}`, `POST /uploads/{id}/activate`.
* **Validation:** UTF‑8; **CRLF** (CSV); required headers; `school_code>0`; digit folding; **formula‑guard**; safe ZIP extraction.
* **Atomic store & manifest:** persist under `sha256/<digest>` with `upload_manifest.json`.
* **Activate:** only one active roster per `year` (locking/txn).
* **Performance:** prefer streaming/chunking; avoid full in‑memory loads.

### Exports — `SABT_V1` (**primary optimization target**)

* Start `POST /exports?format=xlsx|csv` (default: `xlsx`); status `GET /exports/{id}`.
* **Stable sort:** `(year_code, reg_center, group_code, coalesce(school_code,999999), national_id)` (memory‑efficient).
* **Chunking:** default 50,000 rows; XLSX default: **single file, multi‑sheet** (tune chunk size).
* **Excel safety:** UTF‑8; **CRLF**; optional BOM; **always‑quote** sensitive columns; **formula‑guard**; strip control chars.
* **Finalize atomically:** write parts → `fsync` → replace; write `export_manifest.json` **after** files.
* **Evidence (Excel Safety):** `src/utils/excel_safety.py::make_excel_safe`
* **Evidence (Export Logic):** `src/services/export.py::export_to_csv`, `src/services/export.py::export_to_xlsx`

---

## 6) Observability & Minimal Security

* **Metrics (examples):** `export_jobs_total`, `export_duration_seconds`, `uploads_total`, `db_query_latency_seconds`, `cache_hit_ratio`.
* **Logs:** structured JSON; include `correlation_id`, operation context, retry counts, **query durations**, **cache hit/miss**; **no raw PII**.

---

## 7) Performance & Reliability (PRIMARY)

* **Budgets:** Export **p95 < 15s/100k**, **p99 < 20s**, **Mem < 150MB**; health/readiness **p95 < 200ms**.
* **Measurement:** use `time.perf_counter` (latency), **cProfile** (CPU), **tracemalloc** (memory) in tests.
* **Retries:** exponential backoff + **deterministic BLAKE2‑seeded jitter**; inject `sleep_fn` in tests (no real `sleep`).
* **Concurrency:** cap job concurrency; backpressure; pool timeouts; load tests (≥100 concurrent where applicable).
* **Evidence (Retry):** `src/utils/retry.py::retry_with_backoff`
* **Evidence (Redis):** `config/redis.py`

---

## 8) Testing & CI Gates (with performance harness)

* **Warnings = 0** (`--warnings=error`).
* **Freeze/mocks** for TTL/backoff/time; **no sleeps**.
* **State hygiene:** clean **Redis/DB/tmp** pre/post; unique namespaces; **reset CollectorRegistry**.
* **Middleware order test** for POST paths must pass.
* **Performance harness:** tests must assert **p50/p95/p99** and **memory deltas** against budgets.
* **Evidence Map:** each spec item (sections **§1–§15**) must have ≥1 **exact evidence** (`path::symbol` or `tests::name`).
* **Strict Scoring v2** enforced in CI; totals **auto‑capped below 100** if any **skipped/xfailed/warnings > 0**.

**Pytest summary parsing (CI gate):**

```
= N passed, M failed, K xfailed, S skipped, W warnings
```

CI fails if `xfailed + skipped + warnings > 0` or budgets unmet.

---

## 9) RBAC, Audit & Retention (maintenance‑only)

* RBAC: ADMIN (global) vs MANAGER (center‑scoped). Enforce on API/UI.
* Audit (append‑only): record `UPLOAD_*`, `EXPORT_*`, `AUTHN_*` with `ts` from injected clock, `actor_role`, `outcome`. **No PII**.
* Retention: monthly archives (CSV/JSON **Excel‑safe** + manifest), WORM‑style; purge only after valid archive exists.

---

## 10) User‑Visible Errors (Persian, deterministic)

* `UPLOAD_VALIDATION_ERROR`: «فایل نامعتبر است؛ ستون school_code الزامی است.»
* `EXPORT_VALIDATION_ERROR`: «درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.»
* `RATE_LIMIT_EXCEEDED`: «محدودیت درخواست؛ لطفاً کمی صبر کنید.»
* `UNAUTHORIZED`: «دسترسی غیرمجاز؛ لطفاً وارد شوید.»

---

## 11) Operational Mode — Debug‑First (80/20)

1. **Analyze & profile:** Apply the **5‑Layer** framework (§13) + cProfile + tracemalloc; **quantify** issues (e.g., p95=22s; +50MB).
2. **Minimal fix:** smallest possible change (algorithm/batching/async/caching; remove N+1).
3. **Verify:** add/update edge/concurrency/perf tests; budgets must pass.
4. **Report:** output Diagnostic + Quality reports (when requested by pipeline).

> **Code Generation Mode** only if a minimal new feature is strictly required; always honor budgets & guardrails.

---

## 12) Agent Playbook (debug/perf tasks)

* **Locate bottlenecks:** flame graphs; focus exporter & hot paths.
* **Reduce memory:** prefer streaming/chunking over full loads; use tracemalloc for leaks.
* **Fix flaky tests:** 5‑Layer; capture state snapshots; mock external deps.
* **Optimize DB access:** remove N+1; indexes; prefetch/batching; `EXPLAIN ANALYZE`.
* **Endpoint reality fixes:** if tests hit non‑existent path, align to **actual** OpenAPI/routers.

**Quality Assessment (Performance‑Focused):**

```
TOTAL: __/100 → Level: [Excellent/Good/Average/Poor]
Compliance:
- Budgets met: ✅/❌ — evidence: <tests::perf_test>
- Clock injection: ✅/❌ — evidence: <path::symbol>
- State cleanup: ✅/❌ — evidence: <tests::fixture>
- Minimal change: ✅/❌ — evidence: [__ lines in diff]
- Root cause identified: ✅/❌ — evidence: [Diagnostic]
Pytest: passed=__, failed=__, xfailed=__, skipped=__, warnings=__
Next Actions: [ ] (Empty → eligible 100/100)
```

---

## 13) Debugging & RCA Framework (5 layers)

* **L1 Symptoms:** exception/message/stacktrace, frequency; **quantified perf impact** (e.g., +7s p95).
* **L2 State:** Redis keys/TTLs, DB tx, middleware order, connection pools.
* **L3 Timing:** stage breakdown via `perf_counter`, **cProfile** CPU, I/O vs compute.
* **L4 Environment:** CI vs local diffs, versions, timeouts, **tracemalloc** snapshots.
* **L5 Concurrency:** race windows, contention, pool exhaustion, deadlocks.

**Anti‑patterns → replacements:**

* `datetime.now()` → injected `clock.now()`
* direct file writes → **atomic write** pattern
* random jitter → **deterministic** BLAKE2‑seeded jitter
* N+1 queries → batching/prefetch
* full‑memory file loads → streaming/chunking
* blocking I/O in async context → `asyncio.to_thread()` or proper async libs

**Evidence (Debug Helpers):** `src/utils/debug.py::capture_debug_snapshot`, `tests/fixtures/debug.py::debug_context`, `tests/performance/*`

---

## 14) Definition of Done (performance‑first)

* [ ] **Performance budgets met** (export p95/p99/mem) with tests; Pytest **Warnings=0**; evidence added.
* [ ] No wall‑clock; injected **Asia/Tehran** clock only; tests freeze time.
* [ ] Middleware order test passes; state hygiene and CollectorRegistry reset.
* [ ] The change is the **minimal possible** to solve the problem.
* [ ] 5‑Layer Analysis completed and reports generated.

---

## 15) Quick Reference & Decision Tree (perf‑centric)

* **Budgets:** Export **p95 < 15s/100k**, **p99 < 20s**, Mem **< 150MB** | Health **p95 < 200ms**.
* **Primary tools:** `cProfile`, `tracemalloc`, `time.perf_counter`, 5‑Layer RCA.
* **Security (maintenance‑only):** preserve existing guards (`/metrics` token; signed URLs, TTL=3600s); do not extend.
* **Tests:** `clean_state`, `injected_clock` fixtures required | Warnings = 0 | Evidence per §1–§15.
* **Decision:** All tasks start in **Debug‑First**; Code Generation only if strictly necessary.

---

### Appendix A — Reproducibility Block (print in reports)

```
Commit: $(git rev-parse HEAD)
Branch: $(git branch --show-current)
AGENTS.md: v5.2
Python: $(python --version)
OS: $(uname -a || ver)
Repro: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -k <test> --warnings=error
```

### Appendix B — Evidence Map (example)

```
§5 Excel Safety → src/utils/excel_safety.py::make_excel_safe; tests/excel/test_excel_safety.py::test_formula_guard
§3 Atomic IO → src/utils/atomic.py::write_atomic; tests/io/test_atomic_io.py::test_atomic_replace
§7 Retry Policy → src/utils/retry.py::retry_with_backoff; tests/retry/test_backoff.py::test_deterministic_jitter
```
