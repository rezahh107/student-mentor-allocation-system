# AGENTS.md — Reza / ImportToSabt

A single, predictable brief for **AI coding agents** working on this repository.
Keep responses **deterministic, safe, and testable**. Never leak PII. Never guess env/secrets.

> Spec background: AGENTS.md is a simple, open format for guiding coding agents (a README for agents). See the public spec/examples.  
> Preferred file name is **AGENTS.md** at repo root.

---

## 1) Project TL;DR

- **Stack:** Python 3.11+, FastAPI, PostgreSQL, Redis, SSR (Jinja2 + HTMX).
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

- **Install:** `python -m venv .venv && source .venv/bin/activate && pip install -e .`
- **Run tests (no plugins, async ready):**  
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -p pytest_asyncio`
- **Dev server (adjust entrypoint if different):**  
  `uvicorn src.main:app --reload`
- **Lint/Sec (typical):** `ruff check . && bandit -q -r src`

If tests rely on Redis/PostgreSQL, use local services or docker-compose. Clean **Redis/DB/tmp** **before & after** tests; use **unique namespaces** per test; **reset Prometheus CollectorRegistry**.

---

## 3) Absolute Guardrails (do/do-not)

- ✅ **Verify** middleware order `RateLimit → Idempotency → Auth` on POST paths.
- ✅ **Inject** `Clock(tz="Asia/Tehran")` everywhere (naming, manifests, timestamps). Never call `datetime.now()` directly.
- ✅ **Emit** Prometheus metrics (retry/exhaustion); JSON logs must include Correlation-ID and **mask/hash** of identifiers.
- ✅ **Respect** Excel-safety for CSV/XLSX (see §5).
- ✅ **Write** artifacts atomically (`.part` → `fsync` → `rename`).
- ✅ **RBAC:** ADMIN (global) vs MANAGER (center-scoped). `/metrics` via **read-only token**. **Downloads** only via **signed-URL** with TTL and `kid` rotation.
- ❌ Do **NOT** change middleware order, emit PII, depend on wall-clock, or skip state cleanup.
- ❌ Do **NOT** bypass token-guard on `/metrics` or return unsigned downloads.

---

## 4) Domain Rules (normalization & validation)

- **Text normalization:** NFKC, unify `ی/ك`, strip ZW/control, trim.
- **Phone after folding:** `^09\d{9}$`.
- **Enums:** `reg_center ∈ {0,1,2}`, `reg_status ∈ {0,1,3}` (reject others).
- **Derived:** `StudentType` derived from `SpecialSchoolsRoster(year)`.

**Counter & Year (for SABT):**
- gender→prefix map `{0:'373', 1:'357'}`.
- counter regex `^\d{2}(357|373)\d{4}$`.
- **Year code** from `AcademicYearProvider` (**never** `now()`).

---

## 5) Uploads & Exports (strict)

### Uploads — `ROSTER_V1`
- API: `POST /uploads` (`.csv | .zip | .xlsx` ≤ 50MB), `GET /uploads/{id}`, `POST /uploads/{id}/activate`.
- **Validation:** UTF-8; **CRLF** (CSV); header required; `school_code>0`; digit folding; **formula-guard**; ZIP extraction safety (no traversal).
- **Atomic store & manifest:** persist under `sha256/<digest>.csv|xlsx` with `upload_manifest.json` (SHA-256, counts, meta, `format` + `excel_safety`).
- **Activate:** only one active roster per `year` (locking/txn).

### Exports — `SABT_V1`
- Start via `POST /exports?format=xlsx|csv` (**default: xlsx**); status `GET /exports/{id}`.
- **Stable sort:** `(year_code, reg_center, group_code, coalesce(school_code,999999), national_id)`.
- **Chunking:** default 50,000 rows; XLSX default: **single file, multi-sheet** (one chunk per sheet).
- **Excel-safety:** UTF-8; **CRLF**; **BOM optional**; **always-quote** `national_id,counter,mobile,mentor_id,school_code`; **formula-guard** for free-text; strip control chars; **Sensitive-as-Text** for XLSX.
- **Finalize atomically:** write each part → `fsync` → rename; write `export_manifest.json` **after** all files; include SHA-256, counts, filters, snapshot/delta markers, `format`, `sheets`.
- **Delta correctness:** `(created_at, id)` windows with **no gap/overlap**.

---

## 6) Observability & Security

- **Metrics (examples):**  
  `export_jobs_total{status,format}`, `export_duration_seconds{phase,format}`,  
  `export_rows_total{format}`, `export_file_bytes_total{format}`,  
  `uploads_total{status,format}`, `upload_errors_total{type}`,  
  `audit_events_total{action,outcome}`, `auth_ok_total`, `auth_fail_total{reason}`.
- **Logs:** structured JSON; include `correlation_id`, op context, retry counts; **no raw PII**.
- **Security:** `/metrics` requires token; download links are **signed-URL** with `kid` rotation (dual-key rollovers).

---

## 7) Performance & Reliability

- **Budgets:** Exporter **p95 < 15s / 100k**, **Mem < 150MB**; health/readiness **p95 < 200ms**.
- **Retries:** exponential backoff + deterministic jitter (BLAKE2-seeded); attempts configurable; emit retry/exhaustion metrics.
- **Concurrency:** cap job concurrency per `center` and globally; apply backpressure; respect connection pool timeouts/circuits.

---

## 8) Testing & CI Gates

- **Warnings = 0** (treat warnings as errors).
- **Freeze/mocks** for TTL/backoff/dates; **no sleeps** for timing.
- **State hygiene:** clean **Redis/DB/tmp** pre/post; unique namespaces/keys; **reset Prometheus CollectorRegistry**.
- **Middleware order test** on POST paths must pass.
- **Evidence Map:** each spec item ≥ 1 **exact evidence** (`path::symbol` or `tests::name`).
- **Pytest summary parsing** and **Strict Scoring v2** enforced; cap totals if skips/xfails/warnings exist.
- **Security tests:** `/metrics` token-guard, unsigned download rejection, No-PII scans for samples.

---

## 9) RBAC, Audit & Retention

- **RBAC:** ADMIN (all centers) vs MANAGER (own center). Enforce on API/UI (SSR+HTMX).
- **Audit (append-only):** record `UPLOAD_*`, `EXPORT_*`, `AUTHN_*`, `CONFIG_REJECTED` with `ts` from injected clock (Asia/Tehran), `actor_role`, `center_scope?`, `request_id`, `outcome`, `error_code?`, `sha256?`. **No PII** in events.
- **Access Review (light):** periodic report generator under `reports/`.
- **Retention:** monthly archives (CSV/JSON **Excel-safe** + manifest SHA-256), WORM-style; integrate with Backup/Restore; purge old partitions **only after** valid archive exists.

---

## 10) User-Visible Errors (Persian, deterministic)

Examples (do not vary wording without approval):
- `UPLOAD_VALIDATION_ERROR`: «فایل نامعتبر است؛ ستون school_code الزامی است.»
- `EXPORT_VALIDATION_ERROR`: «درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.»
- `EXPORT_IO_ERROR`: «خطا در تولید فایل؛ لطفاً دوباره تلاش کنید.»

---

## 11) Agent Playbook (common tasks)

- **Add/modify endpoints:** verify middleware order; enforce RBAC; keep `/metrics` token-guarded; add metrics & JSON logs (no PII); include integration tests.
- **Work on exporter:** maintain Excel-safety & atomic finalize; update manifest & metrics; prove p95/memory with perf harness.
- **Uploads pipeline:** preserve validation and atomic storage; update `upload_manifest.json`; test ZIP traversal defenses and formula-guard.
- **Keys/tokens:** implement dual-key rollovers with `kid`; ensure logs reveal no secrets; add rotation scripts/hooks.

---

## 12) Definition of Done (checklist)

- [ ] No wall-clock; injected **Asia/Tehran** clock only; tests freeze time.  
- [ ] Middleware order test passes; state hygiene and CollectorRegistry reset.  
- [ ] Metrics/logs updated; `/metrics` remains token-guarded; downloads signed.  
- [ ] Excel-safety preserved; artifacts written atomically; manifests complete.  
- [ ] Budgets met (export p95/mem); Pytest summary shows **Warnings=0**; evidence added.

---
