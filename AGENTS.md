# AGENTS.md — ImportToSabt Project (v5.2-LOCAL • Performance-First, Debug-First 80/20)

> **This file is the single source of truth for all AI debugging/performance agents.**
> **LOCAL-ONLY VERSION: All security features removed for local development**

**Default operating mode:** **80% debugging & optimization / 20% minimal code changes (only when unavoidable).**
Keep responses **deterministic, efficient, and testable**.

---

## 0) Reality Map (MANDATORY pre-step)

Before any analysis or patch:

1. Read this file; record **AGENTS version** (`v5.2-LOCAL`).
2. Enumerate **entrypoints** (e.g., `main:app`) and **routers**; fetch `app.openapi()` paths.
3. Print the **middleware order graph** for **POST** paths.
4. Capture environment snapshot: Python version, OS, important env vars, service reachability (DB/Redis).

**Abort** if AGENTS version mismatch or OpenAPI cannot be loaded.

---

## 1) Project TL;DR

* **Stack:** Python **3.11.9 (CI pinned)**, FastAPI, PostgreSQL, Redis, SSR (Jinja2 + HTMX).
* **Primary focus:** Performance & Debugging — find/fix bottlenecks, memory leaks, and concurrency issues.
* **Determinism:** All time reads via an **injected Clock**; **IANA tz = Asia/Tehran** (no wall-clock). Tests **freeze/mock** time.
* **Python standards:** PEP 8, type hints (PEP 484/526), readability over cleverness, 3.11 idioms (async/await for I/O, `functools.lru_cache`, `dataclasses` where appropriate).
* **Excel safety:** UTF-8, CRLF, optional BOM, **always-quote** sensitive columns, **formula-guard** (`'` prefix), NFKC, digit folding, unify `ی/ک`.
* **Atomic I/O:** write to `.part` → `fsync` → atomic `os.replace`/rename.
* **Middleware order (MUST on POST):** `RateLimit → Idempotency → Auth` (verified by tests).
* **Performance budgets:** Export **p95 < 15s / 100k**, **p99 < 20s**, **Mem < 150MB**; Health **p95 < 200ms**.
* **Observability:** JSON logs with **Correlation-ID**, structured metrics.
* **Endpoint reality:** Discover only from registered **routers & OpenAPI**. **Never invent paths.**
* **User-visible errors:** **Persian**, deterministic; internals/docs may be English.

---

## 2) Setup & Environment

### 2.1) Python Version Policy

* **CI/Containers:** **exact 3.11.9** (must equal `python --version`).
* **Local dev:** **3.11.x** accepted; warn if minor > 9.

```bash
# Verify Python version
python --version  # Expected: Python 3.11.9 (CI) or 3.11.x (local)
```

### 2.2) Environment Variables (Local Development)

```bash
# === Required ===
DATABASE_URL=postgresql://localhost/importosabt
REDIS_URL=redis://localhost:6379/0
TZ=Asia/Tehran

# === Optional (Performance Tuning) ===
LOG_LEVEL=DEBUG                    # DEBUG|INFO|WARNING|ERROR
CHUNK_SIZE=50000                   # Export chunk size (default: 50k)
MAX_UPLOAD_SIZE_MB=50              # Max upload file size
EXPORT_WORKER_POOL_SIZE=4          # Concurrent export workers
DB_POOL_SIZE=20                    # Database connection pool
REDIS_MAX_CONNECTIONS=50           # Redis connection pool

# === Development Tools ===
IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS=true  # Enable /docs, /redoc
METRICS_ENDPOINT_ENABLED=true              # Enable /metrics
PROFILING_ENABLED=false                    # Enable cProfile middleware
```

### 2.3) Installation & Commands

```bash
# Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Run tests (strict mode)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q --warnings=error

# Run specific test categories
pytest tests/unit/           # Fast, no I/O
pytest tests/integration/    # DB/Redis required
pytest tests/performance/    # Budget validation
pytest tests/e2e/            # Full workflows

# Dev server with hot reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Lint & type check
ruff check .
mypy src/ --strict

# Performance profiling
python -m cProfile -o profile.stats -m uvicorn main:app
```

### 2.4) Development Utilities

```bash
# Hot reload with auto-restart (requires make)
make dev-watch

# Load testing (requires locust)
locust -f tests/load/locustfile.py --host=http://localhost:8000

# Memory profiling specific endpoint
python -m tracemalloc_profiler scripts/profile_export.py

# Database reset (development only!)
python scripts/reset_dev_db.py
```

### 2.5) Docker Compose (Quick Start)

```bash
# Start services (PostgreSQL + Redis)
docker-compose up -d

# Stop services
docker-compose down

# Clean volumes (reset data)
docker-compose down -v
```

---

## 3) Absolute Guardrails (performance-first do/do-not)

**Do:**

* **Prioritize performance**; fixes cannot regress budgets.
* **Verify** middleware order `RateLimit → Idempotency → Auth` for **POST** paths.
* **Inject** `Clock(tz="Asia/Tehran")`; **no `datetime.now()`/`time.time()` in logic**.
* **Emit** Prometheus metrics; JSON logs include Correlation-ID.
* **Maintain** Excel safety for CSV/XLSX.
* **Write** artifacts atomically (`.part → fsync → replace`).
* **Use type hints** (PEP 484/526) with Pydantic validation.
* **Endpoint reality:** use only OpenAPI/routers.

**Do-not:**

* Use wall-clock time; invent endpoints; skip state cleanup; introduce performance regressions.
* Use `time.sleep()` in async code (use `asyncio.sleep()`).
* Load entire files into memory (use streaming/chunking).
* Write sync DB calls in async contexts (use `asyncio.to_thread()` or async drivers).

---

## 4) Code Standards & Patterns

### 4.1) Type Hints & Validation

```python
from typing import Annotated, Literal, Iterator
from pydantic import BaseModel, Field, validator
from pathlib import Path

class ExportRequest(BaseModel):
    """Export configuration with validated parameters."""
    
    format: Literal["xlsx", "csv"] = "xlsx"
    chunk_size: Annotated[int, Field(gt=0, le=100_000)] = 50_000
    year_code: Annotated[str, Field(pattern=r"^\d{4}$")]
    
    @validator('chunk_size')
    def validate_chunk_size(cls, v):
        if v < 1000:
            raise ValueError("chunk_size must be at least 1000 for efficiency")
        return v

# Usage
request = ExportRequest(format="xlsx", chunk_size=50_000, year_code="1403")
```

### 4.2) Dependency Injection (Clock Pattern)

```python
from typing import Protocol
from datetime import datetime
from zoneinfo import ZoneInfo

class ClockProtocol(Protocol):
    """Abstract clock for time operations (enables testing)."""
    def now(self) -> datetime: ...
    def perf_counter(self) -> float: ...

class Clock:
    """Production clock with timezone awareness."""
    def __init__(self, tz: str = "Asia/Tehran"):
        self.tz = ZoneInfo(tz)
    
    def now(self) -> datetime:
        return datetime.now(self.tz)
    
    def perf_counter(self) -> float:
        return time.perf_counter()

# In tests - use FakeClock:
class FakeClock:
    """Frozen time for deterministic tests."""
    def __init__(self, frozen_time: datetime):
        self._time = frozen_time
        self._perf = 0.0
    
    def now(self) -> datetime:
        return self._time
    
    def advance(self, seconds: float):
        self._time += timedelta(seconds=seconds)
        self._perf += seconds
    
    def perf_counter(self) -> float:
        return self._perf

# Usage in production code:
def export_students(students: Iterator[Student], clock: ClockProtocol):
    start = clock.perf_counter()
    timestamp = clock.now()
    # ... export logic ...
    logger.info(f"Export completed in {clock.perf_counter() - start:.2f}s")
```

### 4.3) Error Handling Standards

```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class ErrorCode(str, Enum):
    """Standardized error codes."""
    UPLOAD_VALIDATION = "UPLOAD_VALIDATION_ERROR"
    EXPORT_VALIDATION = "EXPORT_VALIDATION_ERROR"
    RATE_LIMIT = "RATE_LIMIT_EXCEEDED"
    GENERAL = "GENERAL_ERROR"

@dataclass(frozen=True)
class ErrorResponse:
    """Consistent error response structure."""
    code: ErrorCode
    message_fa: str           # Persian user-facing message
    correlation_id: str       # For log tracing
    timestamp: datetime
    details: dict | None = None  # Technical details (not shown to user)

# Usage in API:
from fastapi import HTTPException

def validate_upload(file: UploadFile) -> None:
    if file.size > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                code=ErrorCode.UPLOAD_VALIDATION,
                message_fa="حجم فایل بیش از حد مجاز است",
                correlation_id=get_correlation_id(),
                timestamp=clock.now(),
                details={"max_size_mb": MAX_SIZE // (1024*1024)}
            ).dict()
        )
```

### 4.4) Performance Monitoring Pattern

```python
from contextlib import contextmanager
import tracemalloc
import logging

logger = logging.getLogger(__name__)

@contextmanager
def profile_section(name: str, clock: ClockProtocol):
    """
    Profile execution time and memory usage.
    
    Usage:
        with profile_section("export_processing", clock):
            process_export(data)
    """
    start_time = clock.perf_counter()
    start_mem = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
    
    try:
        yield
    finally:
        duration = clock.perf_counter() - start_time
        
        if tracemalloc.is_tracing():
            current_mem = tracemalloc.get_traced_memory()[0]
            mem_delta_mb = (current_mem - start_mem) / 1024 / 1024
            logger.info(
                f"{name}: duration={duration:.3f}s, mem_delta={mem_delta_mb:.1f}MB",
                extra={
                    "section": name,
                    "duration_seconds": duration,
                    "memory_delta_mb": mem_delta_mb
                }
            )
        else:
            logger.info(
                f"{name}: duration={duration:.3f}s",
                extra={"section": name, "duration_seconds": duration}
            )
```

### 4.5) Docstring Standards

```python
def export_to_xlsx(
    students: Iterator[Student],
    output_path: Path,
    chunk_size: int = 50_000,
    clock: ClockProtocol | None = None
) -> ExportManifest:
    """
    Export students to XLSX with multi-sheet chunking.
    
    This function uses streaming to minimize memory usage and atomic writes
    to ensure data integrity. Each chunk is written to a separate sheet.
    
    Args:
        students: Lazy iterator of validated Student objects. Will be consumed
            in chunks to maintain O(chunk_size) memory usage.
        output_path: Destination path for final XLSX file. A temporary .part
            file will be created during processing.
        chunk_size: Rows per sheet (default: 50,000). Lower values reduce memory
            but increase file overhead. Must be >= 1000.
        clock: Injected time source for deterministic timestamps. If None,
            uses production Clock with Asia/Tehran timezone.
    
    Returns:
        ExportManifest containing:
            - file_path: Final output path
            - sha256: File checksum for integrity verification
            - row_count: Total students exported
            - sheet_count: Number of sheets created
            - created_at: Export completion timestamp
    
    Raises:
        ExportValidationError: Invalid chunk_size or output_path
        DiskFullError: Insufficient disk space for export
        DatabaseError: Failed to fetch student data
    
    Performance:
        - Memory: O(chunk_size) — constant per chunk, not total rows
        - Time: ~0.15s per 1,000 rows (p95 on reference hardware)
        - Disk: ~500KB per 1,000 rows (XLSX compression applied)
    
    Example:
        >>> from src.services.export import export_to_xlsx
        >>> from src.models.student import Student
        >>> 
        >>> # Streaming query to avoid loading all students
        >>> students = db.query(Student).yield_per(1000)
        >>> manifest = export_to_xlsx(
        ...     students=students,
        ...     output_path=Path("/tmp/export.xlsx"),
        ...     chunk_size=50_000
        ... )
        >>> print(f"Exported {manifest.row_count} students")
    
    Evidence:
        - Implementation: src/services/export.py::export_to_xlsx
        - Tests: tests/integration/test_export.py::test_xlsx_chunking
        - Performance: tests/performance/test_export_budget.py
    """
```

---

## 5) Domain Rules (normalization & validation)

* **Text normalization:** NFKC, unify `ی/ک`, strip zero-width/control, trim.
* **Phone (after folding):** `^09\d{9}$`.
* **Enums:** `reg_center ∈ {0,1,2}`, `reg_status ∈ {0,1,3}` (reject others).
* **Derived:** `StudentType` depends on `SpecialSchoolsRoster(year)`.
* **Year code:** from `AcademicYearProvider` (**never** `now()`). Provide a golden test for the current academic year prefix.
* **Evidence (Core Models):** `src/models/student.py::Student` (or actual path in repo).

---

## 6) Uploads & Exports (strict)

### Uploads — `ROSTER_V1`

* API: `POST /uploads` (`.csv|.zip|.xlsx` ≤ 50MB), `GET /uploads/{id}`, `POST /uploads/{id}/activate`.
* **Validation:** UTF-8; **CRLF** (CSV); required headers; `school_code>0`; digit folding; **formula-guard**; safe ZIP extraction.
* **Atomic store & manifest:** persist under `sha256/<digest>` with `upload_manifest.json`.
* **Activate:** only one active roster per `year` (locking/txn).
* **Performance:** prefer streaming/chunking; avoid full in-memory loads.

### Exports — `SABT_V1` (**primary optimization target**)

* Start `POST /exports?format=xlsx|csv` (default: `xlsx`); status `GET /exports/{id}`.
* **Stable sort:** `(year_code, reg_center, group_code, coalesce(school_code,999999), national_id)` (memory-efficient).
* **Chunking:** default 50,000 rows; XLSX default: **single file, multi-sheet** (tune chunk size).
* **Excel safety:** UTF-8; **CRLF**; optional BOM; **always-quote** sensitive columns; **formula-guard**; strip control chars.
* **Finalize atomically:** write parts → `fsync` → replace; write `export_manifest.json` **after** files.
* **Evidence (Excel Safety):** `src/utils/excel_safety.py::make_excel_safe`
* **Evidence (Export Logic):** `src/services/export.py::export_to_csv`, `src/services/export.py::export_to_xlsx`

---

## 7) Observability

* **Metrics (examples):** `export_jobs_total`, `export_duration_seconds`, `uploads_total`, `db_query_latency_seconds`, `cache_hit_ratio`.
* **Logs:** structured JSON; include `correlation_id`, operation context, retry counts, **query durations**, **cache hit/miss**.

---

## 8) Performance & Reliability (PRIMARY)

### 8.1) Performance Budgets

| Operation          | p50   | p95   | p99   | Memory | Notes             |
| ------------------ | ----- | ----- | ----- | ------ | ----------------- |
| Export (100k rows) | 10s   | 15s   | 20s   | 150MB  | Streaming XLSX    |
| Upload validation  | 2s    | 5s    | 8s    | 100MB  | CSV parsing       |
| Health check       | 50ms  | 200ms | 500ms | 10MB   | DB ping + Redis   |
| API endpoints      | 100ms | 500ms | 1s    | 50MB   | Standard requests |

### 8.2) Measurement Tools

```python
# Latency measurement
import time

start = time.perf_counter()
result = perform_operation()
duration = time.perf_counter() - start
logger.info(f"Operation took {duration:.3f}s")

# CPU profiling
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()
perform_operation()
profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions

# Memory profiling
import tracemalloc

tracemalloc.start()
snapshot_before = tracemalloc.take_snapshot()
perform_operation()
snapshot_after = tracemalloc.take_snapshot()
top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
for stat in top_stats[:10]:
    print(stat)
```

### 8.3) Retry Policy

* **Retries:** exponential backoff + **deterministic BLAKE2-seeded jitter**; inject `sleep_fn` in tests (no real `sleep`).
* **Concurrency:** cap job concurrency; backpressure; pool timeouts; load tests (≥100 concurrent where applicable).
* **Evidence (Retry):** `src/utils/retry.py::retry_with_backoff`
* **Evidence (Redis):** `config/redis.py`

---

## 9) Testing Strategy

### 9.1) Test Organization

```
tests/
├── unit/              # Pure functions, no I/O, fast (< 1s total)
│   ├── test_normalizer.py
│   ├── test_excel_safety.py
│   └── test_validators.py
├── integration/       # DB/Redis interactions, medium (< 30s total)
│   ├── test_upload_service.py
│   ├── test_export_service.py
│   └── test_cache_layer.py
├── performance/       # Budget validation, slow (< 5min total)
│   ├── test_export_budget.py
│   ├── test_upload_budget.py
│   └── conftest.py    # Performance fixtures
├── e2e/              # Full workflow scenarios
│   ├── test_upload_activate_export.py
│   └── test_error_recovery.py
└── fixtures/         # Shared test data and utilities
    ├── debug.py
    ├── clock.py
    └── sample_data.py
```

### 9.2) Testing Requirements

* **Warnings = 0** (`--warnings=error`).
* **Freeze/mocks** for TTL/backoff/time; **no sleeps**.
* **State hygiene:** clean **Redis/DB/tmp** pre/post; unique namespaces; **reset CollectorRegistry**.
* **Middleware order test** for POST paths must pass.
* **Performance harness:** tests must assert **p50/p95/p99** and **memory deltas** against budgets.
* **Evidence Map:** each spec item (sections §1—§14) must have ≥1 **exact evidence** (`path::symbol` or `tests::name`).
* **Strict Scoring v2** enforced in CI; totals **auto-capped below 100** if any **skipped/xfailed/warnings > 0**.

### 9.3) Pytest Summary Parsing (CI Gate)

```
= N passed, M failed, K xfailed, S skipped, W warnings
```

CI fails if `xfailed + skipped + warnings > 0` or budgets unmet.

### 9.4) Common Test Fixtures

```python
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

@pytest.fixture
def frozen_clock():
    """Provide deterministic clock for tests."""
    return FakeClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tehran")))

@pytest.fixture
def clean_state(redis_client, db_session):
    """Ensure clean state before and after tests."""
    # Clean before test
    redis_client.flushdb()
    db_session.query(Upload).delete()
    db_session.query(Export).delete()
    db_session.commit()
    
    yield
    
    # Clean after test
    redis_client.flushdb()
    db_session.rollback()

@pytest.fixture
def sample_students():
    """Generate sample student data for tests."""
    return [
        Student(
            national_id=f"00123456{i:02d}",
            first_name="علی",
            last_name="احمدی",
            school_code=1001 + i % 10,
            year_code="1403"
        )
        for i in range(100)
    ]
```

---

## 10) User-Visible Errors (Persian, deterministic)

* `UPLOAD_VALIDATION_ERROR`: «فایل نامعتبر است؛ ستون school_code الزامی است.»
* `EXPORT_VALIDATION_ERROR`: «درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید.»
* `RATE_LIMIT_EXCEEDED`: «محدودیت درخواست؛ لطفاً کمی صبر کنید.»
* `GENERAL_ERROR`: «خطایی رخ داده است؛ لطفاً دوباره تلاش کنید.»

---

## 11) Operational Mode — Debug-First (80/20)

1. **Analyze & profile:** Apply the **5-Layer** framework (§13) + cProfile + tracemalloc; **quantify** issues (e.g., p95=22s; +50MB).
2. **Minimal fix:** smallest possible change (algorithm/batching/async/caching; remove N+1).
3. **Verify:** add/update edge/concurrency/perf tests; budgets must pass.
4. **Report:** output Diagnostic + Quality reports (when requested by pipeline).

> **Code Generation Mode** only if a minimal new feature is strictly required; always honor budgets & guardrails.

---

## 12) Agent Playbook (debug/perf tasks)

* **Locate bottlenecks:** flame graphs; focus exporter & hot paths.
* **Reduce memory:** prefer streaming/chunking over full loads; use tracemalloc for leaks.
* **Fix flaky tests:** 5-Layer; capture state snapshots; mock external deps.
* **Optimize DB access:** remove N+1; indexes; prefetch/batching; `EXPLAIN ANALYZE`.
* **Endpoint reality fixes:** if tests hit non-existent path, align to **actual** OpenAPI/routers.

**Quality Assessment (Performance-Focused):**

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

### Anti-patterns → Replacements

| ❌ Anti-pattern          | ✅ Replacement                                    | Evidence                                   |
| ----------------------- | ------------------------------------------------ | ------------------------------------------ |
| `datetime.now()`        | Injected `clock.now()`                           | `src/utils/clock.py::Clock`                |
| Direct file writes      | Atomic write pattern (`.part → fsync → replace`) | `src/utils/atomic.py::write_atomic`        |
| Random jitter           | Deterministic BLAKE2-seeded jitter               | `src/utils/retry.py::deterministic_jitter` |
| N+1 queries             | Batching/prefetch with `yield_per()`             | `src/services/export.py::batch_query`      |
| Full-memory file loads  | Streaming/chunking with iterators                | `src/services/export.py::stream_students`  |
| `time.sleep()` in async | `asyncio.sleep()`                                | All async code                             |
| Sync DB in async        | `asyncio.to_thread()` or async driver            | `src/database/async_session.py`            |
| Missing `async with`    | Proper context managers                          | All async resources                        |

**Evidence (Debug Helpers):** 

- `src/utils/debug.py::capture_debug_snapshot`
- `tests/fixtures/debug.py::debug_context`
- `tests/performance/*`

---

## 14) Definition of Done (performance-first)

* [ ] **Performance budgets met** (export p95/p99/mem) with tests; Pytest **Warnings=0**; evidence added.
* [ ] No wall-clock; injected **Asia/Tehran** clock only; tests freeze time.
* [ ] Middleware order test passes; state hygiene and CollectorRegistry reset.
* [ ] The change is the **minimal possible** to solve the problem.
* [ ] 5-Layer Analysis completed and reports generated.
* [ ] All new code has type hints and docstrings (§4.5 standard).
* [ ] Tests added in appropriate category (unit/integration/performance/e2e).

---

## 15) Quick Reference & Decision Tree (perf-centric)

### Performance Budgets

```
Export (100k):  p95 < 15s  |  p99 < 20s  |  Mem < 150MB
Health check:   p95 < 200ms  |  p99 < 500ms  |  Mem < 10MB
```

### Primary Tools

- **Profiling:** `cProfile`, `tracemalloc`, `time.perf_counter`
- **Analysis:** 5-Layer RCA framework
- **Testing:** `pytest` with `--warnings=error`

### Decision Tree

```
Is this a bug/performance issue?
├─ YES → Debug-First mode (80%)
│  ├─ Profile with cProfile + tracemalloc
│  ├─ Apply 5-Layer RCA
│  ├─ Minimal fix (algorithm/batching/async)
│  └─ Verify with tests + budgets
└─ NO → Is new feature strictly necessary?
   ├─ YES → Code Generation mode (20%)
   │  ├─ Follow all guardrails
   │  ├─ Add type hints + docstrings
   │  └─ Performance tests required
   └─ NO → SKIP (maintain focus on performance)
```

### Common Commands

```bash
# Profile export performance
python -m cProfile -o export.prof scripts/benchmark_export.py
python -m pstats export.prof

# Memory leak detection
python -m tracemalloc scripts/check_memory_leak.py

# Run performance tests only
pytest tests/performance/ -v

# Check specific budget
pytest tests/performance/test_export_budget.py::test_100k_export_budget
```

---

## 16) CI/CD Optimization

### GitHub Actions Configuration

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11.9"]
        test-group: [1, 2, 3, 4]  # Parallel execution
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-xdist pytest-cov
      
      - name: Parallel test execution
        run: |
          pytest -n auto --dist loadscope \
                 --splits 4 --group ${{ matrix.test-group }} \
                 --warnings=error \
                 --cov=src --cov-report=xml
        env:
          PYTEST_XDIST_WORKER_COUNT: 4
          PYTEST_DISABLE_PLUGIN_AUTOLOAD: 1
          DATABASE_URL: postgresql://postgres:postgres@localhost/test_db
          REDIS_URL: redis://localhost:6379/15
          TZ: Asia/Tehran
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
          fail_ci_if_error: false
      
      - name: Performance budget check
        run: |
          pytest tests/performance/ -v --tb=short
        continue-on-error: false
      
      - name: Check for warnings
        run: |
          if grep -q "warnings" pytest.log; then
            echo "::error::Tests generated warnings - CI blocked"
            exit 1
          fi
```

### Local CI Simulation

```bash
# Simulate CI environment locally
docker run -it --rm \
  -v $(pwd):/app \
  -w /app \
  -e DATABASE_URL=postgresql://postgres:postgres@db/test_db \
  -e REDIS_URL=redis://redis:6379/15 \
  python:3.11.9 \
  bash -c "pip install -e . && pytest -q --warnings=error"
```

---

## 17) Appendices

### Appendix A — Reproducibility Block (print in reports)

```bash
Commit: $(git rev-parse HEAD)
Branch: $(git branch --show-current)
AGENTS.md: v5.2-LOCAL
Python: $(python --version)
OS: $(uname -a || ver)
Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Repro: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -k <test> --warnings=error
```

### Appendix B — Evidence Map (examples)

```
§4.1 Type Hints → src/models/export.py::ExportRequest; tests/unit/test_validation.py::test_export_request_validation
§4.2 Clock Injection → src/utils/clock.py::Clock; tests/fixtures/clock.py::frozen_clock
§4.3 Error Handling → src/api/errors.py::ErrorResponse; tests/unit/test_errors.py::test_error_response_structure
§4.4 Performance Profiling → src/utils/profiling.py::profile_section; tests/performance/test_profiling.py
§6 Excel Safety → src/utils/excel_safety.py::make_excel_safe; tests/unit/test_excel_safety.py::test_formula_guard
§6 Export Logic → src/services/export.py::export_to_xlsx; tests/integration/test_export.py::test_xlsx_chunking
§8 Atomic IO → src/utils/atomic.py::write_atomic; tests/unit/test_atomic_io.py::test_atomic_replace
§8 Retry Policy → src/utils/retry.py::retry_with_backoff; tests/unit/test_retry.py::test_deterministic_jitter
§9 Test Fixtures → tests/fixtures/clock.py::frozen_clock; tests/fixtures/debug.py::clean_state
§13 Debug Framework → src/utils/debug.py::capture_debug_snapshot; tests/fixtures/debug.py::debug_context
```

### Appendix C — Performance Checklist

Before submitting performance-related changes:

```
[ ] Profiled with cProfile - identified hotspots
[ ] Measured memory with tracemalloc - no leaks detected
[ ] Ran performance tests - all budgets pass
    [ ] Export p95 < 15s for 100k rows
    [ ] Export p99 < 20s for 100k rows
    [ ] Export memory < 150MB peak
    [ ] Health check p95 < 200ms
[ ] Verified no N+1 queries (use EXPLAIN ANALYZE)
[ ] Streaming/chunking used (no full-memory loads)
[ ] Clock injected (no datetime.now() or time.time())
[ ] Atomic writes implemented (.part → fsync → replace)
[ ] Tests added/updated with performance assertions
[ ] All pytest warnings = 0
[ ] State cleanup verified (Redis/DB/tmp/CollectorRegistry)
[ ] Correlation-ID in all logs
[ ] Type hints added for new code
[ ] Docstrings follow §4.5 standard
[ ] Evidence added to map (path::symbol)
```

### Appendix D — Common Performance Issues & Solutions

| Issue                         | Symptom                     | Solution                                  | Evidence                                  |
| ----------------------------- | --------------------------- | ----------------------------------------- | ----------------------------------------- |
| **N+1 Queries**               | Export p95 > 30s            | Use `yield_per()` + `joinedload()`        | `src/services/export.py::batch_query`     |
| **Memory Leak**               | Memory grows over time      | Use iterators, not lists; `del` after use | `src/services/export.py::stream_students` |
| **Blocking I/O in async**     | Health check p95 > 1s       | Use `asyncio.to_thread()` or async libs   | `src/api/health.py::health_check`         |
| **Full file in memory**       | Upload fails for 50MB files | Stream with `yield` or chunking           | `src/services/upload.py::stream_csv`      |
| **Missing indexes**           | DB query > 5s               | Add indexes on sort/filter columns        | `migrations/001_add_indexes.sql`          |
| **Connection pool exhausted** | Timeouts under load         | Increase pool size or add backpressure    | `config/database.py::POOL_SIZE`           |
| **Redis key explosion**       | Redis memory > 1GB          | Use TTL, prefix keys, expire old data     | `src/cache/redis.py::set_with_ttl`        |

### Appendix E — Quick Debug Commands

```bash
# Check current performance
python scripts/benchmark.py --export --rows 100000

# Profile specific function
python -c "
import cProfile
from src.services.export import export_to_xlsx
cProfile.run('export_to_xlsx(...)', sort='cumulative')
"

# Find memory leaks
python -m tracemalloc scripts/check_leaks.py

# Check database query performance
psql $DATABASE_URL -c "EXPLAIN ANALYZE SELECT * FROM students WHERE year_code='1403' ORDER BY national_id LIMIT 100000;"

# Monitor Redis memory
redis-cli --stat

# Check connection pools
python scripts/check_pools.py

# Simulate load
locust -f tests/load/export_load.py --headless -u 100 -r 10 -t 5m

# Generate flame graph
python -m cProfile -o profile.stats scripts/benchmark_export.py
flameprof profile.stats > flame.svg

# Check for deadlocks
python scripts/detect_deadlocks.py --timeout 30
```

### Appendix F — Troubleshooting Guide

#### Problem: Tests fail with "warnings detected"

```bash
# Solution 1: Run with verbose warnings
pytest -v -W default

# Solution 2: Find specific warning source
pytest --tb=long 2>&1 | grep -A5 "DeprecationWarning"

# Solution 3: Fix or suppress specific warning
# In conftest.py:
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="some_module")
```

#### Problem: Export exceeds memory budget

```bash
# Solution: Profile memory usage
python -m tracemalloc scripts/profile_export.py --rows 100000

# Check for memory growth pattern
import tracemalloc
tracemalloc.start()
# ... run export ...
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

#### Problem: Flaky test failures

```bash
# Solution 1: Run test multiple times
pytest tests/integration/test_export.py::test_concurrent_exports -v --count=50

# Solution 2: Add debug logging
pytest -v -s --log-cli-level=DEBUG

# Solution 3: Use debug_context fixture
def test_flaky_scenario(debug_context):
    with debug_context.capture():
        # ... test code ...
    debug_context.print_snapshot()  # Shows state on failure
```

#### Problem: Redis connection errors

```bash
# Check Redis availability
redis-cli ping

# Check connection count
redis-cli info clients | grep connected_clients

# Solution: Reset connections
redis-cli CLIENT KILL TYPE normal
python scripts/reset_redis_pool.py
```

#### Problem: Database deadlocks

```bash
# Check for locks
psql $DATABASE_URL -c "SELECT * FROM pg_locks WHERE NOT granted;"

# Solution: Add proper transaction ordering
# In code:
with db.begin():
    # Always acquire locks in same order
    db.query(Table1).with_for_update().filter(...).first()
    db.query(Table2).with_for_update().filter(...).first()
```

---

## 18) Version History

### v5.2-LOCAL (Current)

- ✅ Removed all security features for local development
- ✅ Added comprehensive code standards and patterns (§4)
- ✅ Enhanced environment configuration (§2.2)
- ✅ Added development utilities and Docker Compose support
- ✅ Expanded testing strategy with fixtures examples (§9)
- ✅ Added CI/CD optimization section (§16)
- ✅ Added comprehensive appendices (A-F)
- ✅ Added performance budgets table (§8.1)
- ✅ Added anti-patterns table with evidence (§13)
- ✅ Added troubleshooting guide (Appendix F)

### v5.2

- Original version with security features
- RBAC, audit logs, and retention policies
- Token-based metrics authentication
- Signed URLs for downloads

### v5.1 and earlier

- Deprecated - do not use

---

## 19) Contact & Support

### Getting Help

1. **Documentation Issues**: Open issue on GitHub with `[DOCS]` prefix
2. **Performance Questions**: Tag with `[PERFORMANCE]` and include profiling data
3. **Bug Reports**: Use 5-Layer RCA format and include reproducibility block

### Performance Optimization Requests

When requesting performance optimization:

```markdown
**Current Performance:**
- Operation: Export 100k students to XLSX
- p50: 12s, p95: 22s, p99: 35s
- Memory: 280MB peak

**Target Budget:**
- p95 < 15s
- p99 < 20s
- Memory < 150MB

**Profiling Data:**
[Attach cProfile output and tracemalloc snapshot]

**Reproducibility:**
Commit: abc123def
Branch: main
AGENTS.md: v5.2-LOCAL
Python: 3.11.9
Repro: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/performance/test_export_budget.py::test_100k_export -v
```

---

## Summary

This document (v5.2-LOCAL) is optimized for **local development** with:

✅ **Zero security overhead** - no RBAC, tokens, or signed URLs  
✅ **Performance-first** - 80/20 debug/code split with strict budgets  
✅ **Practical patterns** - Clock injection, type hints, error handling  
✅ **Complete testing** - unit/integration/performance/e2e with fixtures  
✅ **Rich tooling** - profiling, debugging, CI/CD optimization  
✅ **Comprehensive appendices** - evidence map, checklists, troubleshooting  

**Remember:** Every change must pass performance budgets and maintain deterministic behavior. Use the 5-Layer RCA framework for all debugging. Keep responses testable and minimal.

**Version:** v5.2-LOCAL  
**Last Updated:** 2024-01-15  
**Compatibility:** Python 3.11.9+ only
