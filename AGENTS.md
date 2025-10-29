# AGENTS.md — ImportToSabt Project

A single, predictable brief for **AI coding agents** working on this repository.
Keep responses **deterministic, safe, and testable**. Never leak PII. Never guess env/secrets.

> Spec background: AGENTS.md is a simple, open format for guiding coding agents (a README for agents). See the public spec/examples.  
> Preferred file name is **AGENTS.md** at repo root.

---

## 1) Project TL;DR

- **Stack:** Python **3.11.9 (pin)**, FastAPI, PostgreSQL, Redis, SSR (Jinja2 + HTMX).
- **Determinism:** All time reads via **injected clock**; **IANA tz = Asia/Tehran** (no wall-clock). Tests **freeze/mocks** time.
- **Security & Privacy:** JSON logs with **Correlation-ID**; **No raw PII** (mask/hash). `/metrics` is **token-guarded**; downloads use **signed-URL**.
- **Excel-safety:** UTF-8, CRLF, BOM (optional), **always-quote** sensitive columns, **formula-guard** (`'`), NFKC + digit folding + unify `ی/ك`.
- **Atomic I/O:** write to `.part` → `fsync` → atomic rename.
- **Middleware order (MUST):** `RateLimit → Idempotency → Auth` (verified by tests).
- **Performance budgets:** explicit **p95 latency** & **memory caps**; exporter baseline **p95 < 15s / 100k**, **Mem < 150MB**.
- **End-user errors:** **Persian** and **deterministic** (internals/docs can be English).

References: Phase-1 (SSR+HTMX/determinism), Phase-2 (ROSTER_V1 upload), Phase-3 (SABT_V1 export), Phase-6 (Ops dashboards & token-guard /metrics), Phase-7 (Audit UX), Phase-8 (Access/RBAC & signed URLs), Phase-9 (UAT/SLO), Phase-11 (Audit retention), Phase-12 (post-go-live perf/cost). See repo docs.

---

## 2) Setup & Commands

> Agents should **run tests locally** and **fail fast** on warnings; assume shared CI runners and flaky infra (use retries with deterministic jitter).

- **Python:** use **3.11.9 exactly** (`python --version` must equal `3.11.9`).
- **Install:** `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- **Run tests (no plugins, async ready):**
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`
- **Dev server (adjust entrypoint if different):**
  `uvicorn main:app --reload`
- **Lint/Sec (typical):** `ruff check . && bandit -q -r src`

If tests rely on Redis/PostgreSQL, use local services or docker-compose. Clean **Redis/DB/tmp** **before & after** tests; use **unique namespaces** per test; **reset Prometheus CollectorRegistry**.

## Windows Smoke & Acceptance

1. Python **3.11.9** را نصب و بررسی کنید: `python --version` → `3.11.9`.
2. در PowerShell (UTF-8) و در ریشهٔ ریپو اجرا کنید:
   ```powershell
   $env:IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS = "true"
   $env:METRICS_TOKEN = "dev-metrics"
   python scripts\hooks\no_src_main_check.py
   ```
3. `.\run_application.bat` را اجرا کنید و Uvicorn را فعال نگه دارید (ورودی: `main:app`).
4. در شل دوم دستور زیر را اجرا کنید تا خروجی JSON/LOG ذخیره شود:
   ```powershell
   pwsh -NoLogo -File .\run_server_check.ps1 -OutputJsonPath windows_check.json -OutputLogPath windows_check.log
   ```
5. انتظار نتایج:
   - `/openapi.json`, `/docs`, `/redoc` → کد 200 زمانی که `PUBLIC_DOCS=1`.
   - `/metrics` بدون هدر → کد 403.
   - `/metrics` با `Authorization: Bearer dev-metrics` → کد 200.

## CI Integration

<!-- CI badge removed for portability. Run smoke tests locally with the provided PowerShell scripts. -->
- Workflow: `.github/workflows/windows-smoke.yml`
- Strict Scoring v2: pipeline fails if `tools/ci/parse_pytest_summary.py` reports **TOTAL < 100**.
- Determinism: parser/tests avoid wall-clock calls; timing uses monotonic measurements only for diagnostics.

> **No-100 Gate:** اگر هر کدام از `skipped`, `xfailed`, یا `warnings` بزرگ‌تر از صفر باشد، امتیاز **به‌صورت خودکار زیر 100** کَپ می‌شود و CI شکست می‌خورد.

---

## 3) Absolute Guardrails (do/do-not)

- ✅ **Verify** middleware order `RateLimit → Idempotency → Auth` on POST paths.
- ✅ **Inject** `Clock(tz="Asia/Tehran")` everywhere. Never call `datetime.now()` directly.
- ✅ **Emit** Prometheus metrics; JSON logs must include Correlation-ID and **mask/hash** of identifiers.
- ✅ **Respect** Excel-safety for CSV/XLSX (see §5).
- ✅ **Write** artifacts atomically (`.part` → `fsync` → `rename`).
- ✅ **RBAC:** ADMIN (global) vs MANAGER (center-scoped). `/metrics` via **read-only token**. **Downloads** only via **signed-URL** with TTL and **kid rotation**.
- ❌ Do **NOT** change middleware order, emit PII, depend on wall-clock, or skip state cleanup.
- ❌ Do **NOT** bypass token-guard on `/metrics` or return unsigned downloads.

---

## 4) Domain Rules (normalization & validation)

- **Text normalization:** NFKC, unify `ی/ك`, strip ZW/control, trim.
- **Phone after folding:** `^09\d{9}$`.
- **Enums:** `reg_center ∈ {0,1,2}`, `reg_status ∈ {0,1,3}` (reject others).
- **Derived:** `StudentType` derived from `SpecialSchoolsRoster(year)`.
- **Year code** from `AcademicYearProvider` (**never** `now()`).
- **Evidence (Core Models):** `src/models/student.py::Student`

---

## 5) Uploads & Exports (strict)

### Uploads — `ROSTER_V1`
- API: `POST /uploads` (`.csv | .zip | .xlsx` ≤ 50MB), `GET /uploads/{id}`, `POST /uploads/{id}/activate`.
- **Validation:** UTF-8; **CRLF** (CSV); header required; `school_code>0`; digit folding; **formula-guard**; ZIP extraction safety.
- **Atomic store & manifest:** persist under `sha256/<digest>` with `upload_manifest.json`.
- **Activate:** only one active roster per `year` (locking/txn).

### Exports — `SABT_V1`
- Start via `POST /exports?format=xlsx|csv` (**default: xlsx**); status `GET /exports/{id}`.
- **Stable sort:** `(year_code, reg_center, group_code, coalesce(school_code,999999), national_id)`.
- **Chunking:** default 50,000 rows; XLSX default: **single file, multi-sheet**.
- **Excel-safety:** UTF-8; **CRLF**; **BOM optional**; **always-quote** sensitive columns; **formula-guard**; strip control chars.
- **Finalize atomically:** write parts → `fsync` → rename; write `export_manifest.json` **after** all files.
- **Evidence (Excel Safety):** `src/utils/excel_safety.py::make_excel_safe`
- **Evidence (Export Logic):** `src/services/export.py::export_to_csv`, `src/services/export.py::export_to_xlsx`

---

## 6) Observability & Security

- **Metrics (examples):** `export_jobs_total`, `export_duration_seconds`, `uploads_total`, `audit_events_total`, `auth_fail_total`.
- **Logs:** structured JSON; include `correlation_id`, op context, retry counts; **no raw PII**.
- **Security:** `/metrics` requires token; download links are **signed-URL** with `kid` rotation.
- **Default TTL:** **3600s (1h)** unless overridden in project settings.
- **Evidence (Token Guard):** `src/middleware/auth.py::metrics_token_guard`
- **Evidence (Security Tests):** `tests/security/test_metrics_token_guard.py`

---

## 7) Performance & Reliability

- **Budgets:** Exporter **p95 < 15s / 100k**, **Mem < 150MB**; health/readiness **p95 < 200ms**.
- **Retries:** exponential backoff + deterministic jitter (BLAKE2-seeded).
- **Concurrency:** cap job concurrency; apply backpressure; respect connection pool timeouts.
- **Evidence (Retry Pattern):** `src/utils/retry.py::retry_with_backoff`
- **Evidence (Redis Config):** `config/redis.py`

---

## 8) Testing & CI Gates

- **Warnings = 0** (treat warnings as errors).
- **Freeze/mocks** for TTL/backoff/dates; **no sleeps** for timing.
- **State hygiene:** clean **Redis/DB/tmp** pre/post; unique namespaces; **reset Prometheus CollectorRegistry**.
- **Middleware order test** on POST paths must pass.
- **Evidence Map:** each spec item ≥ 1 **exact evidence** (`path::symbol` or `tests::name`).
- **Scope:** at least **1 Evidence** is required for each section from **§1 to §15**; missing evidence will incur a score penalty.
- **Strict Scoring v2** enforced; cap totals if skips/xfails/warnings exist.
- **Evidence (Essential Fixtures):** `tests/fixtures/state.py::clean_state`, `tests/fixtures/time.py::injected_clock`
- **Evidence (Middleware Test):** `tests/integration/test_middleware.py::test_middleware_order_on_post_endpoints`

---

## 9) RBAC, Audit & Retention

- **RBAC:** ADMIN (all centers) vs MANAGER (own center). Enforce on API/UI.
- **Audit (append-only):** record `UPLOAD_*`, `EXPORT_*`, `AUTHN_*` with `ts` from injected clock, `actor_role`, `outcome`. **No PII**.
- **Retention:** monthly archives (CSV/JSON **Excel-safe** + manifest), WORM-style; purge old partitions **only after** valid archive exists.

---

## 10) User-Visible Errors (Persian, deterministic)

- `UPLOAD_VALIDATION_ERROR`: «فایل نامعتبر است؛ ستون school_code الزامی است.»
- `EXPORT_VALIDATION_ERROR`: «درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.»
- `RATE_LIMIT_EXCEEDED`: «محدودیت درخواست؛ لطفاً کمی صبر کنید.»
- `UNAUTHORIZED`: «دسترسی غیرمجاز؛ لطفاً وارد شوید.»

---

## 11) Agent Operational Modes

### Mode A: Code Generation + Quality Assessment
When generating **new code or features**:
1. **Generate** code complying with all AGENTS.md requirements.
2. **Output** a Quality Assessment Report immediately after code.

### Mode B: Debugging + Root Cause Analysis
When analyzing **existing code, errors, or failures**:
1. **Apply** the 5-Layer Diagnostic Framework (§13).
2. **Provide** evidence-based fixes with exact file/line references.
3. **Include** prevention checklist and reproduction steps.

---

## 12) Agent Playbook (common tasks)

- **Add/modify endpoints:** verify middleware order; enforce RBAC; add metrics & JSON logs (no PII); include integration tests.
- **Work on exporter:** maintain Excel-safety & atomic finalize; update manifest & metrics; prove p95/memory with perf harness.
- **Uploads pipeline:** preserve validation and atomic storage; update `upload_manifest.json`; test ZIP traversal defenses.
- **Debug flaky tests:** Use 5-Layer framework; capture state snapshots; check CI vs local environment diffs.

**Quality Assessment Report Format (Mode A):**
```
════════ QUALITY ASSESSMENT REPORT ════════
TOTAL: __/100 → Level: [Excellent/Good/Average/Poor]

AGENTS.md Compliance:
├─ Clock injection (Asia/Tehran): ✅/❌ — evidence: <path::symbol>
├─ Middleware order verified: ✅/❌ — evidence: <tests::test_name>
├─ State cleanup (before/after): ✅/❌ — evidence: <path::fixture>
├─ Excel-safety preserved: ✅/❌ — evidence: <path::function>
└─ /metrics token-guard: ✅/❌ — evidence: <path::endpoint>

Next Actions:
[ ] [Specific task with acceptance criteria]
[ ] (Empty list = eligible for 100/100)
```

---

## 13) Debugging & RCA Framework

When analyzing errors, follow the **5-Layer methodology**:

- **L1 Symptoms:** Exception type, message, stacktrace, frequency pattern (e.g., 15% flaky).
- **L2 State:** Redis keys/TTLs, DB transactions, middleware order, connection pools.
- **L3 Timing:** Per-stage breakdown, bottlenecks, network/compute split.
- **L4 Environment:** CI vs local diffs, resources, dependency versions, timeouts.
- **L5 Concurrency:** Race windows, resource contention, pool exhaustion.

**Common Anti-Patterns to Flag:**
- `datetime.now()` → **USE** injected `clock.now()`
- direct file write → **USE** atomic write pattern
- random jitter → **USE** deterministic jitter

**Evidence (Debug Helpers):** `src/utils/debug.py::capture_debug_snapshot`, `tests/fixtures/debug.py::debug_context`

---

## 14) Definition of Done (checklist)

- [ ] No wall-clock; injected **Asia/Tehran** clock only; tests freeze time.
- [ ] Middleware order test passes; state hygiene and CollectorRegistry reset.
- [ ] Metrics/logs updated; `/metrics` remains token-guarded; downloads signed.
- [ ] Excel-safety preserved; artifacts written atomically; manifests complete.
- [ ] Budgets met (export p95/mem); Pytest summary shows **Warnings=0**; evidence added.
- [ ] Quality Assessment Report generated (Mode A) or 5-Layer Analysis completed (Mode B).

---

## 15) Quick Reference & Decision Tree

- **Budgets:** Export **p95 < 15s/100k**, Mem **< 150MB** | Health **p95 < 200ms**.
- **Security:** `/metrics` → Token | Downloads → Signed URLs (TTL=3600s, kid rotation) | Logs → No raw PII.
- **Tests:** `clean_state`, `injected_clock` fixtures required | Warnings = 0 | Evidence per §1–§15.
- **Decision:** New feature → **Mode A** | Bug/error → **Mode B** | Unclear → **Ask**.
```
