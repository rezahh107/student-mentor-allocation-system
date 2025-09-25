"""Command-line interface wiring allocation engine, exporter, GUI, and telemetry."""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.core.logging_config import setup_logging

setup_logging()

from src.observe.perf import PerformanceObserver
from src.phase3_allocation.contracts import AllocationConfig
from src.phase3_allocation.engine import AllocationEngine
from src.phase3_allocation.policy import EligibilityPolicy
from src.phase3_allocation.providers import ManagerCentersProvider, SpecialSchoolsProvider
from src.tools.export_excel_safe import ExcelSafeExporter, iter_rows, normalize_cell
from src.ui.trace_index import TraceFilterIndex
from src.ui.trace_viewer import (
    TraceViewerApp,
    TraceViewerRow,
    TraceViewerStorage,
    TraceViewerStorageWriter,
    render_text_ui,
)

LOGGER = logging.getLogger(__name__)
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@dataclass
class CsvStudent:
    student_id: str
    gender: object | None
    group_code: object | None
    reg_center: object | None
    reg_status: object | None
    edu_status: object | None
    school_code: object | None
    student_type: object | None
    roster_year: object | None


@dataclass
class CsvMentor:
    mentor_id: object
    gender: object | None
    allowed_groups: List[object]
    allowed_centers: List[object]
    capacity: object
    current_load: object
    is_active: object
    mentor_type: object
    special_schools: List[object]
    manager_id: object | None


class CsvSpecialSchoolsProvider(SpecialSchoolsProvider):
    def __init__(self, mapping: Mapping[int, frozenset[int]]):
        self._mapping = dict(mapping)

    def get(self, year: int) -> frozenset[int] | None:
        return self._mapping.get(year)


class CsvManagerCentersProvider(ManagerCentersProvider):
    def __init__(self, mapping: Mapping[int, frozenset[int]]):
        self._mapping = dict(mapping)

    def get_allowed_centers(self, manager_id: int) -> frozenset[int] | None:
        return self._mapping.get(manager_id)


def _split_values(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace(";", "|").split("|") if item.strip()]


def _parse_bool(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower() if value is not None else ""
    if text in {"1", "true", "y", "yes", "on"}:
        return True
    if text in {"0", "false", "n", "no", "off", ""}:
        return False
    raise ValueError("مقدار بولی ناشناخته است.")


def _sanitize_text(value: object | None) -> str:
    return normalize_cell(value)


def _persian_number(value: int) -> str:
    """Convert integers to Persian digits with thousands separators."""

    formatted = f"{value:,}".replace(",", "٬")
    return formatted.translate(_PERSIAN_DIGITS)


def _load_mentors(path: Path, *, limit: int) -> tuple[List[CsvMentor], Dict[int, frozenset[int]], Dict[int, frozenset[int]]]:
    mentors: List[CsvMentor] = []
    manager_mapping: Dict[int, frozenset[int]] = {}
    school_mapping: Dict[int, frozenset[int]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if limit and index >= limit:
                break
            allowed_groups = [_sanitize_text(value) for value in _split_values(row.get("allowed_groups"))]
            allowed_centers = [_sanitize_text(value) for value in _split_values(row.get("allowed_centers"))]
            special_schools = [_sanitize_text(value) for value in _split_values(row.get("special_schools"))]
            manager_id_raw = row.get("manager_id")
            manager_id = manager_id_raw
            if manager_id_raw is not None and str(manager_id_raw).strip() == "":
                manager_id = None
            try:
                is_active_value = _parse_bool(row.get("is_active"))
            except ValueError as exc:
                raise ValueError("مقدار is_active نامعتبر است.") from exc
            mentor = CsvMentor(
                mentor_id=row.get("mentor_id"),
                gender=row.get("gender"),
                allowed_groups=allowed_groups,
                allowed_centers=allowed_centers,
                capacity=row.get("capacity"),
                current_load=row.get("current_load"),
                is_active=is_active_value,
                mentor_type=row.get("mentor_type"),
                special_schools=special_schools,
                manager_id=manager_id,
            )
            mentors.append(mentor)
            manager_centers = _split_values(row.get("manager_centers"))
            if mentor.manager_id is not None and manager_centers:
                try:
                    manager_key = int(_sanitize_text(mentor.manager_id))
                    centers = frozenset(int(_sanitize_text(value)) for value in manager_centers)
                except ValueError:
                    LOGGER.warning("نقشه مراکز مدیر نامعتبر است.")
                else:
                    manager_mapping[manager_key] = centers
            yearly_schools = row.get("special_school_years")
            if yearly_schools:
                for block in yearly_schools.split(";"):
                    if not block.strip():
                        continue
                    if ":" not in block:
                        continue
                    year_text, schools_text = block.split(":", 1)
                    try:
                        year_key = int(_sanitize_text(year_text))
                    except ValueError:
                        continue
                    codes = frozenset(
                        int(_sanitize_text(code))
                        for code in _split_values(schools_text)
                    )
                    if codes:
                        school_mapping[year_key] = codes
            if not yearly_schools and special_schools:
                fallback_codes = frozenset(
                    int(_sanitize_text(code)) for code in special_schools if _sanitize_text(code)
                )
                if fallback_codes:
                    school_mapping.setdefault(0, fallback_codes)
    return mentors, manager_mapping, school_mapping


def _load_students(path: Path, *, limit: int) -> Iterator[CsvStudent]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if limit and index >= limit:
                break
            yield CsvStudent(
                student_id=row.get("student_id", str(index)),
                gender=row.get("gender"),
                group_code=row.get("group_code"),
                reg_center=row.get("reg_center"),
                reg_status=row.get("reg_status"),
                edu_status=row.get("edu_status"),
                school_code=row.get("school_code"),
                student_type=row.get("student_type"),
                roster_year=row.get("roster_year"),
            )


def _build_export_row(
    index: int,
    student: CsvStudent,
    best_row: TraceViewerRow | None,
    evaluations: List[TraceViewerRow],
) -> Mapping[str, object]:
    trace_source = best_row.trace if best_row else (evaluations[0].trace if evaluations else [])
    trace_summary = "|".join(
        f"{item['code']}:{'1' if item.get('passed') else '0'}" for item in trace_source
    )
    return {
        "student_index": index,
        "student_id": _sanitize_text(student.student_id),
        "group_code": _sanitize_text(student.group_code),
        "reg_center": _sanitize_text(student.reg_center),
        "selected_mentor_id": best_row.mentor_id if best_row else "",
        "selected_mentor_type": best_row.mentor_type if best_row else "",
        "occupancy_ratio": best_row.occupancy_ratio if best_row else "",
        "current_load": best_row.current_load if best_row else "",
        "trace": trace_summary,
    }


def _build_gui_rows(
    student_index: int,
    student: CsvStudent,
    evaluations: List[TraceViewerRow],
) -> List[TraceViewerRow]:
    group_text = _sanitize_text(student.group_code)
    center_text = _sanitize_text(student.reg_center)
    for row in evaluations:
        row.student_index = student_index
        row.student_group = group_text
        row.student_center = center_text
    return evaluations


def _stream_allocation(
    students: Iterable[CsvStudent],
    mentors: List[CsvMentor],
    engine: AllocationEngine,
    *,
    observer: PerformanceObserver,
    storage_writer: TraceViewerStorageWriter,
) -> Iterator[Mapping[str, object]]:
    for index, student in enumerate(students):
        with observer.measure("allocation_engine.student"):
            best, evaluations = engine.evaluate(student, mentors)
        trace_rows = [
            TraceViewerRow.from_engine_entry(entry, student_index=index)
            for entry in evaluations
        ]
        selected_id = _sanitize_text(getattr(best, "mentor_id", "") if best else "")
        selected_row = None
        for row in trace_rows:
            if selected_id and row.mentor_id == selected_id:
                row.is_selected = True
                selected_row = row
                break
        storage_writer.append_rows(_build_gui_rows(index, student, trace_rows))
        yield _build_export_row(index, student, selected_row, trace_rows)


def _create_policy(
    manager_mapping: Mapping[int, frozenset[int]],
    school_mapping: Mapping[int, frozenset[int]],
) -> EligibilityPolicy:
    special_provider = CsvSpecialSchoolsProvider(school_mapping)
    manager_provider = CsvManagerCentersProvider(manager_mapping)
    return EligibilityPolicy(special_provider, manager_provider, AllocationConfig())


def _persist_telemetry(observer: PerformanceObserver, path: Path, *, fmt: str) -> None:
    summary = observer.summary()
    if fmt == "json":
        summary.to_json(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = summary.stats()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "count", "p50_ms", "p95_ms", "max_ms", "memory_peak_bytes"])
        for label, stat in stats.items():
            writer.writerow(
                [
                    label,
                    stat.count,
                    f"{stat.p50_ms:.6f}",
                    f"{stat.p95_ms:.6f}",
                    f"{stat.max_ms:.6f}",
                    stat.memory_peak_bytes,
                ]
            )
        writer.writerow([])
        writer.writerow(["counter", "name", "value"])
        for name, value in summary.counters.items():
            writer.writerow(["counter", name, value])


def _launch_ui(
    mode: str,
    storage: TraceViewerStorage,
    *,
    page_size: int,
    page: int,
    index: TraceFilterIndex | None = None,
) -> None:
    if mode == "text":
        render_text_ui(
            storage,
            stream=sys.stdout,
            limit=page_size,
            page=page,
            index=index,
        )
        return
    try:
        app = TraceViewerApp.create(
            storage,
            page_size=page_size,
            initial_page=page,
            index=index,
        )
    except RuntimeError as error:
        LOGGER.warning("رابط گرافیکی در دسترس نیست؛ نمایش متنی فعال شد.")
        render_text_ui(
            storage,
            stream=sys.stdout,
            limit=page_size,
            page=page,
            index=index,
        )
        LOGGER.debug("جزئیات خطا رابط گرافیکی", exc_info=error)
        return
    app.start()


def _validate_pagination(
    index: TraceFilterIndex, *, page_size: int, page: int
) -> None:
    if page_size <= 0:
        raise ValueError("اندازه صفحه باید بزرگ‌تر از صفر باشد.")
    if page <= 0:
        raise ValueError("شماره صفحه باید بزرگ‌تر از صفر باشد.")
    stats = index.validate_page({"selected_only": True}, page_size)
    total_rows = stats["total_rows"]
    total_pages = stats["total_pages"]
    if total_rows == 0:
        if page > 1:
            message = (
                f"صفحه { _persian_number(page) } معتبر نیست؛ "
                f"بیشینهٔ صفحه: {_persian_number(total_pages)} "
                f"({_persian_number(total_rows)} ردیف)."
            )
            raise ValueError(message)
        return
    if page > total_pages:
        nearest = max(1, total_pages)
        message = (
            f"صفحه { _persian_number(page) } معتبر نیست؛ "
            f"بیشینهٔ صفحه: {_persian_number(total_pages)} "
            f"({_persian_number(total_rows)} ردیف). "
            f"نزدیک‌ترین صفحهٔ مجاز: {_persian_number(nearest)}."
        )
        raise ValueError(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 allocation CLI")
    parser.add_argument("--in", dest="students", required=True, help="مسیر فایل دانش‌آموزان")
    parser.add_argument("--mentors", dest="mentors", required=True, help="مسیر فایل منتورها")
    parser.add_argument("--out", dest="output", help="مسیر فایل خروجی")
    parser.add_argument("--bom", choices=["utf8", "none"], default="utf8", help="BOM خروجی")
    parser.add_argument(
        "--excel-safe",
        choices=["true", "false"],
        default="true",
        help="فعال‌سازی محافظ فرمول اکسل",
    )
    parser.add_argument("--dry-run", action="store_true", help="عدم تولید فایل خروجی")
    parser.add_argument(
        "--ui",
        nargs="?",
        const="tk",
        choices=["tk", "text"],
        help="نمایش رابط گرافیکی یا متنی",
    )
    parser.add_argument(
        "--text-page-size",
        dest="text_page_size",
        type=int,
        default=20,
        help="تعداد ردیف‌های هر صفحه در حالت متنی",
    )
    parser.add_argument(
        "--text-page",
        dest="text_page",
        type=int,
        default=1,
        help="شماره صفحه برای خروجی متنی",
    )
    parser.add_argument("--limit", type=int, default=10000, help="حداکثر ردیف‌های ورودی")
    parser.add_argument(
        "--telemetry-out",
        dest="telemetry_out",
        help="مسیر ذخیره‌سازی آمار کارایی",
    )
    parser.add_argument(
        "--telemetry-format",
        dest="telemetry_format",
        choices=["json", "csv"],
        default="json",
        help="قالب خروجی آمار کارایی",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    student_path = Path(args.students)
    mentor_path = Path(args.mentors)
    if not student_path.exists():
        LOGGER.error("فایل دانش‌آموزان یافت نشد.")
        return 1
    if not mentor_path.exists():
        LOGGER.error("فایل منتورها یافت نشد.")
        return 1

    mentors, manager_map, school_map = _load_mentors(mentor_path, limit=args.limit)
    policy = _create_policy(manager_map, school_map)
    observer = PerformanceObserver()
    engine = AllocationEngine(policy=policy, observer=observer)
    storage_writer = TraceViewerStorageWriter()
    export_stream = _stream_allocation(
        _load_students(student_path, limit=args.limit),
        mentors,
        engine,
        observer=observer,
        storage_writer=storage_writer,
    )

    include_bom = args.bom == "utf8"
    excel_safe = args.excel_safe == "true"
    headers = [
        "student_index",
        "student_id",
        "group_code",
        "reg_center",
        "selected_mentor_id",
        "selected_mentor_type",
        "occupancy_ratio",
        "current_load",
        "trace",
    ]
    if not args.dry_run:
        if not args.output:
            LOGGER.error("مسیر خروجی تعیین نشده است.")
            return 1
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        exporter = ExcelSafeExporter(headers=headers)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            exporter.export(
                export_stream,
                handle,
                include_bom=include_bom,
                excel_safe=excel_safe,
            )
    else:
        for _ in iter_rows(export_stream, headers=headers, excel_safe=excel_safe):
            continue

    storage = storage_writer.finalize()

    LOGGER.info("آمار زمان‌بندی: %s", observer.stats_snapshot())
    LOGGER.info("شمارنده‌ها: %s", observer.counters_snapshot())

    if args.telemetry_out:
        _persist_telemetry(
            observer,
            Path(args.telemetry_out),
            fmt=args.telemetry_format,
        )

    if args.ui:
        index = TraceFilterIndex(storage)
        try:
            _validate_pagination(
                index,
                page_size=args.text_page_size,
                page=args.text_page,
            )
        except ValueError as error:
            LOGGER.error(str(error))
            storage.cleanup()
            return 1
        try:
            _launch_ui(
                args.ui,
                storage,
                page_size=args.text_page_size,
                page=args.text_page,
                index=index,
            )
        except (RuntimeError, ValueError) as error:
            LOGGER.error(str(error))
        finally:
            storage.cleanup()
    else:
        storage.cleanup()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

