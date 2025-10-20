from __future__ import annotations

import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4
from zipfile import ZipFile

import pytest
from freezegun import freeze_time

from sma.phase6_import_to_sabt.export_writer import ExportWriter, atomic_writer
from sma.phase6_import_to_sabt.sanitization import deterministic_jitter, sanitize_text
from sma._local_fakeredis import FakeStrictRedis
from tests.integration.conftest import InMemorySession, RedisNamespace


@pytest.fixture
def frozen_tehran_time() -> Iterator[freeze_time]:
    """Freeze time to Asia/Tehran for deterministic exporter behaviour."""

    with freeze_time("2024-03-20T10:00:00+0330", tz_offset=3.5) as frozen:
        yield frozen


@pytest.fixture
def excel_state() -> Iterator[RedisNamespace]:
    """Provide a namespaced Redis context with cleanup before/after tests."""

    client = FakeStrictRedis()
    namespace = f"tests:excel:{uuid4().hex}"
    client.flushdb()
    context = RedisNamespace(client=client, namespace=namespace)
    try:
        yield context
    finally:
        leaked = context.keys()
        client.flushdb()
        if leaked:
            pytest.fail(f"کلیدهای ردیس پاک‌سازی نشدند: {leaked}")


@pytest.fixture
def excel_db_session() -> Iterator[InMemorySession]:
    """Create an isolated in-memory DB session with enforced rollback."""

    session = InMemorySession()
    try:
        yield session
    finally:
        asyncio.run(session.rollback())
        if not session.verify_foreign_keys():
            pytest.fail("نقض کلید خارجی پس از تست مشاهده شد.")


@pytest.fixture
def excel_debug_context(
    excel_state: RedisNamespace, excel_db_session: InMemorySession
) -> Callable[[dict | None], dict[str, object]]:
    """Return a callable that enriches failure diagnostics with state information."""

    def _collect(extra: dict | None = None) -> dict[str, object]:
        context = {
            "timestamp": time.time(),
            "namespace": excel_state.namespace,
            "redis_keys": excel_state.keys(),
            "db_queries": excel_db_session.queries,
        }
        if extra:
            context.update(extra)
        return context

    return _collect


def run_with_backoff(
    assertion: Callable[[], None],
    *,
    frozen,
    seed: str,
    context_builder: Callable[[dict], dict],
    attempts: int = 3,
    base_delay: float = 0.05,
) -> None:
    """Execute *assertion* with deterministic exponential backoff and jitter."""

    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            assertion()
            return
        except AssertionError as exc:
            errors.append(str(exc))
            if attempt == attempts:
                context = context_builder({"errors": errors, "attempts": attempt})
                raise AssertionError(
                    "Excel safety assertion failed after retries; context=" + json.dumps(context, ensure_ascii=False)
                ) from exc
            jitter = deterministic_jitter(base_delay, attempt, seed)
            frozen.tick(jitter)


@pytest.mark.integration
@pytest.mark.excel
@pytest.mark.excel_safety
@pytest.mark.retry_logic
@pytest.mark.cleanup
@pytest.mark.middleware
def test_always_quote_preserves_formulas(
    excel_state: RedisNamespace,
    excel_debug_context: Callable[[dict | None], dict[str, object]],
    excel_db_session: InMemorySession,
    frozen_tehran_time,
    tmp_path: Path,
) -> None:
    """Ensure CSV exports always quote sensitive cells and guard formulas safely."""

    excel_db_session.record_query("/* excel_quote */ SELECT 1")
    namespace_key = excel_state.key("excel-quote")
    excel_state.client.set(namespace_key, "pending")
    writer = ExportWriter(sensitive_columns=("national_id", "mobile"), formula_guard=True)
    export_dir = tmp_path / "quote"
    export_dir.mkdir(parents=True, exist_ok=True)

    def path_factory(index: int) -> Path:
        return export_dir / f"export-{index}.csv"

    risky_formula = "=SUM(A1:A2)"
    long_text = "بسیار" + (" طولانی" * 50) + "\u200cمتن"
    rows = [
        {
            "national_id": risky_formula,
            "counter": "00012345",
            "first_name": long_text,
            "last_name": "کاظمی\u200cنیا",
            "gender": 1,
            "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
            "reg_center": 1,
            "reg_status": 0,
            "group_code": "A",
            "student_type": "ویژه",
            "school_code": "۱۲۳",
            "mentor_id": "mentor-۱",
            "mentor_name": "زهرا",
            "mentor_mobile": "09121234567",
            "allocation_date": "1402-01-01",
            "year_code": "02",
        }
    ]

    def _assert_csv() -> None:
        result = writer.write_csv(rows, path_factory=path_factory)
        assert result.excel_safety["always_quote"], "always_quote flag missing"
        csv_path = result.files[0].path
        with csv_path.open("r", encoding="utf-8") as handle:
            reader = list(csv.reader(handle))
        assert reader[1][0].startswith("'=SUM"), excel_debug_context({"cell": reader[1][0]})
        sanitized_first = sanitize_text(long_text)
        assert reader[1][2] == sanitized_first, excel_debug_context({"first_name": reader[1][2]})
        raw_line = csv_path.read_text(encoding="utf-8").splitlines()[1]
        assert '"09123456789"' in raw_line, excel_debug_context({"raw": raw_line})

    try:
        run_with_backoff(
            _assert_csv,
            frozen=frozen_tehran_time,
            seed=namespace_key,
            context_builder=lambda extra: excel_debug_context(
                {
                    "namespace": excel_state.namespace,
                    "extra": extra,
                }
            ),
        )
    finally:
        excel_state.client.delete(namespace_key)


@pytest.mark.integration
@pytest.mark.excel
@pytest.mark.excel_safety
@pytest.mark.retry_logic
@pytest.mark.cleanup
@pytest.mark.middleware
def test_atomic_write_prevents_corruption(
    excel_state: RedisNamespace,
    excel_debug_context: Callable[[dict | None], dict[str, object]],
    excel_db_session: InMemorySession,
    frozen_tehran_time,
    tmp_path: Path,
) -> None:
    """Verify atomic_writer cleans up .part files after failures and commits on success."""

    excel_db_session.record_query("/* excel_atomic */ SELECT 1")
    namespace_key = excel_state.key("excel-atomic")
    excel_state.client.set(namespace_key, "pending")
    target = tmp_path / "atomic.csv"

    with pytest.raises(RuntimeError):
        with atomic_writer(target, newline="\r\n") as handle:
            handle.write("header\n")
            raise RuntimeError("simulated failure")

    part_path = target.with_suffix(".csv.part")
    assert not target.exists(), excel_debug_context({"target": str(target)})
    assert not part_path.exists(), excel_debug_context({"part": str(part_path)})

    def _assert_success() -> None:
        with atomic_writer(target, newline="\r\n") as handle:
            handle.write("ok\n")
        assert target.exists(), excel_debug_context({"target": str(target)})
        content = target.read_bytes()
        assert content == b"ok\r\n", excel_debug_context({"content": content})

    try:
        run_with_backoff(
            _assert_success,
            frozen=frozen_tehran_time,
            seed=namespace_key,
            context_builder=lambda extra: excel_debug_context({"target": str(target), "extra": extra}),
        )
    finally:
        excel_state.client.delete(namespace_key)


@pytest.mark.integration
@pytest.mark.excel
@pytest.mark.excel_safety
@pytest.mark.retry_logic
@pytest.mark.cleanup
@pytest.mark.middleware
def test_chunked_csv_handles_mixed_digits(
    excel_state: RedisNamespace,
    excel_debug_context: Callable[[dict | None], dict[str, object]],
    excel_db_session: InMemorySession,
    frozen_tehran_time,
    tmp_path: Path,
) -> None:
    """Exporter should normalize digits and stream chunks without leaking temporary files."""

    excel_db_session.record_query("/* excel_chunk */ SELECT 1")
    namespace_key = excel_state.key("excel-chunks")
    excel_state.client.set(namespace_key, "pending")
    writer = ExportWriter(sensitive_columns=("national_id", "mobile", "mentor_id"), chunk_size=10)
    export_dir = tmp_path / "chunked"
    export_dir.mkdir(parents=True, exist_ok=True)

    def path_factory(index: int) -> Path:
        return export_dir / f"chunk-{index}.csv"

    rows = []
    long_payload = "متن" + (" کشیده" * 200) + " پایان"
    for index in range(0, 37):
        rows.append(
            {
                "national_id": f"{index:010d}",
                "counter": index,
                "first_name": long_payload,
                "last_name": "الف\u200cب",
                "gender": index % 2,
                "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
                "reg_center": str(index % 3),
                "reg_status": str((index + 1) % 4),
                "group_code": "0" if index % 5 == 0 else "A",
                "student_type": "عادی",
                "school_code": "۱۲۳",
                "mentor_id": "۰۱۲۳۴۵۶",
                "mentor_name": "معلم",
                "mentor_mobile": "09121111111",
                "allocation_date": "1402-02-{:02d}".format((index % 28) + 1),
                "year_code": "02",
            }
        )

    def _assert_chunks() -> None:
        result = writer.write_csv(rows, path_factory=path_factory)
        assert result.total_rows == len(rows), excel_debug_context({"total_rows": result.total_rows})
        assert len(result.files) == 4, excel_debug_context({"files": [f.path.name for f in result.files]})
        for exported in result.files:
            assert exported.path.exists(), excel_debug_context({"missing": exported.path.as_posix()})
            with exported.path.open("r", encoding="utf-8") as handle:
                table = list(csv.reader(handle))
            first_row = table[1]
            assert first_row[0].isdigit() and len(first_row[0]) == 10
            assert first_row[11] == "0123456", excel_debug_context({"mentor_id": first_row[11]})
            raw_line = exported.path.read_text(encoding="utf-8").splitlines()[1]
            assert '"09123456789"' in raw_line, excel_debug_context({"raw": raw_line})

    try:
        run_with_backoff(
            _assert_chunks,
            frozen=frozen_tehran_time,
            seed=namespace_key,
            context_builder=lambda extra: excel_debug_context({"extra": extra}),
        )
    finally:
        excel_state.client.delete(namespace_key)


@pytest.mark.integration
@pytest.mark.excel
@pytest.mark.excel_safety
@pytest.mark.retry_logic
@pytest.mark.cleanup
@pytest.mark.middleware
def test_xlsx_sensitive_columns_marked_as_text(
    excel_state: RedisNamespace,
    excel_debug_context: Callable[[dict | None], dict[str, object]],
    excel_db_session: InMemorySession,
    frozen_tehran_time,
    tmp_path: Path,
) -> None:
    """XLSX export must store sensitive columns as text with guarded formulas."""

    excel_db_session.record_query("/* excel_xlsx */ SELECT 1")
    namespace_key = excel_state.key("excel-xlsx")
    excel_state.client.set(namespace_key, "pending")
    writer = ExportWriter(sensitive_columns=("national_id", "mobile", "mentor_id"), chunk_size=5)
    export_dir = tmp_path / "xlsx"
    export_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "national_id": "=1+1",
            "counter": 77,
            "first_name": "یوسف",
            "last_name": "کریم",
            "gender": 0,
            "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
            "reg_center": 2,
            "reg_status": 1,
            "group_code": "B",
            "student_type": "عادی",
            "school_code": "۱۲۳",
            "mentor_id": "۰۱۲۳۴۵۶",
            "mentor_name": "مربی",
            "mentor_mobile": "09129999999",
            "allocation_date": "1402-03-10",
            "year_code": "02",
        }
    ]

    def _assert_xlsx() -> None:
        result = writer.write_xlsx(rows, path_factory=lambda _: export_dir / "export.xlsx")
        exported = result.files[0]
        with ZipFile(exported.path) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            styles = archive.read("xl/styles.xml").decode("utf-8")
        assert "'=1+1" in sheet, excel_debug_context({"sheet": sheet[:200]})
        assert "formatCode=\"@\"" in styles, excel_debug_context({"styles": styles[:200]})

    try:
        run_with_backoff(
            _assert_xlsx,
            frozen=frozen_tehran_time,
            seed=namespace_key,
            context_builder=lambda extra: excel_debug_context({"extra": extra}),
        )
    finally:
        excel_state.client.delete(namespace_key)


@pytest.mark.integration
@pytest.mark.excel
@pytest.mark.excel_safety
@pytest.mark.retry_logic
@pytest.mark.cleanup
@pytest.mark.middleware
def test_manifest_records_excel_safety_metadata(
    excel_state: RedisNamespace,
    excel_debug_context: Callable[[dict | None], dict[str, object]],
    excel_db_session: InMemorySession,
    frozen_tehran_time,
    tmp_path: Path,
) -> None:
    """Manifest should expose Excel safety metadata for downstream audits."""

    excel_db_session.record_query("/* excel_manifest */ SELECT 1")
    namespace_key = excel_state.key("excel-manifest")
    excel_state.client.set(namespace_key, "pending")
    writer = ExportWriter(sensitive_columns=("national_id", "mobile", "mentor_id"), include_bom=True)
    export_dir = tmp_path / "manifest"
    export_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "national_id": "۹۸۷۶۵۴۳۲۱۰",
            "counter": None,
            "first_name": None,
            "last_name": "",
            "gender": "0",
            "mobile": None,
            "reg_center": 0,
            "reg_status": 3,
            "group_code": "",
            "student_type": "عادی",
            "school_code": "",
            "mentor_id": "",
            "mentor_name": None,
            "mentor_mobile": "",
            "allocation_date": "1402-04-15",
            "year_code": "02",
        }
    ]

    def _assert_manifest() -> None:
        result = writer.write_csv(rows, path_factory=lambda _: export_dir / "manifest.csv")
        safety = result.excel_safety
        assert safety["always_quote"], excel_debug_context(safety)
        assert set(safety["always_quote_columns"]) == {"national_id", "mobile", "mentor_id"}
        assert safety["bom"], excel_debug_context(safety)
        csv_path = result.files[0].path
        with csv_path.open("r", encoding="utf-8-sig") as handle:
            data = list(csv.reader(handle))
        raw_line = csv_path.read_text(encoding="utf-8-sig").splitlines()[1]
        assert '"9876543210"' in raw_line, excel_debug_context({"row": data[1], "raw": raw_line})

    try:
        run_with_backoff(
            _assert_manifest,
            frozen=frozen_tehran_time,
            seed=namespace_key,
            context_builder=lambda extra: excel_debug_context({"extra": extra}),
        )
    finally:
        excel_state.client.delete(namespace_key)
