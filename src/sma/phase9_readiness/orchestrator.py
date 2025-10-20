from __future__ import annotations

import csv
import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from hashlib import blake2b, sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, MutableMapping, Sequence

from pydantic import BaseModel, Field, field_validator

from sma.core.normalize import normalize_digits
from sma.phase2_counter_service.academic_year import AcademicYearProvider
from sma.shared.counter_rules import COUNTER_PREFIX_MAP
from sma.reliability.clock import Clock
from sma.reliability.logging_utils import JSONLogger

from .metrics import ReadinessMetrics
from .pilot import StreamingPilotMeter
from .retention import RetentionValidator
from .retry import RetryPolicy


_ZERO_WIDTH = {0x200c, 0x200d, 0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e}
_SENSITIVE_COLUMNS = {"شماره تماس", "phone", "owner_phone", "identifier", "student_id"}
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _strip_zero_width(value: str) -> str:
    return "".join(ch for ch in value if ord(ch) not in _ZERO_WIDTH)


def _canonical_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = normalize_digits(unicodedata.normalize("NFKC", text))
    text = _strip_zero_width(text)
    return text.strip()


def _fold_phone(value: Any) -> str:
    digits = _canonical_text(value)
    if not digits:
        raise ValueError("شماره تماس الزامی است.")
    if digits.startswith("0098") and len(digits) > 4:
        digits = "0" + digits[4:]
    if digits.startswith("098") and len(digits) > 3:
        digits = "0" + digits[3:]
    if digits.startswith("98") and len(digits) > 2:
        digits = "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    if not digits.startswith("09") or len(digits) != 11 or not digits.isdigit():
        raise ValueError("شماره تماس باید با ۰۹ شروع شود و ۱۱ رقم باشد.")
    return digits


def _validate_enum(value: Any, *, allowed: set[str], field: str) -> str:
    text = _canonical_text(value)
    if text not in allowed:
        raise ValueError(f"{field} مجاز نیست.")
    return text


def _validate_counter(counter: Any) -> str:
    text = _canonical_text(counter)
    if not text:
        raise ValueError("شناسه شمارنده خالی است.")
    if not text.isdigit() or len(text) != 9:
        raise ValueError("شناسه شمارنده باید ۹ رقم باشد.")
    if text[2:5] not in COUNTER_PREFIX_MAP.values():
        raise ValueError("شناسه شمارنده باید با 357/373 باشد.")
    return text


class TokenConfig(BaseModel):
    metrics_read: str = Field(min_length=16)
    download_signing: str = Field(min_length=32)

    model_config = dict(extra="forbid")


class DSNConfig(BaseModel):
    redis: str
    postgres: str

    model_config = dict(extra="forbid")


class EnvironmentConfig(BaseModel):
    namespace: str = Field(min_length=3)
    tokens: TokenConfig
    dsns: DSNConfig

    model_config = dict(extra="forbid")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "EnvironmentConfig":
        payload: dict[str, Any] = {
            "namespace": env.get("READINESS_NAMESPACE", "uat"),
            "tokens": {
                "metrics_read": env["READINESS_METRICS_TOKEN"],
                "download_signing": env["READINESS_SIGNING_SECRET"],
            },
            "dsns": {
                "redis": env["READINESS_REDIS_DSN"],
                "postgres": env["READINESS_PG_DSN"],
            },
        }
        return cls(**payload)


class AcceptanceChecklistItem(BaseModel):
    id: str
    requirement: str
    spec_reference: str
    owner: str
    evidence_path: str | None = None

    model_config = dict(extra="forbid")

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        text = _canonical_text(value)
        if not text:
            raise ValueError("شناسه پذیرش خالی است.")
        return text


class UATScenario(BaseModel):
    scenario_id: str
    title: str
    description: str
    checklist_ids: Sequence[str]
    criticality: str
    registration_center: str
    registration_status: str
    owner_phone: str
    counter_id: str
    academic_year: str

    model_config = dict(extra="forbid")

    @field_validator("scenario_id", "title", "description", "criticality")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        text = _canonical_text(value)
        if not text:
            raise ValueError("مقدار متنی خالی است.")
        return text

    @field_validator("registration_center")
    @classmethod
    def _center(cls, value: str) -> str:
        return _validate_enum(
            value,
            allowed={"0", "1", "2"},
            field="کد مرکز",
        )

    @field_validator("registration_status")
    @classmethod
    def _status(cls, value: str) -> str:
        return _validate_enum(
            value,
            allowed={"0", "1", "3"},
            field="وضعیت ثبت‌نام",
        )

    @field_validator("checklist_ids")
    @classmethod
    def _checklist(cls, values: Sequence[str]) -> Sequence[str]:
        cleaned = [_canonical_text(value) for value in values]
        if not cleaned:
            raise ValueError("لیست پذیرش خالی است.")
        return cleaned

    @field_validator("owner_phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return _fold_phone(value)

    @field_validator("counter_id")
    @classmethod
    def _counter(cls, value: str) -> str:
        return _validate_counter(value)


@dataclass(slots=True)
class PilotStageResult:
    name: str
    duration_seconds: float
    memory_mb: float
    errors: list[str]


@dataclass(slots=True)
class PilotReport:
    run_id: str
    correlation_id: str
    stages: list[PilotStageResult]
    row_count: int
    dataset_bytes: int
    dataset_checksum: str
    stream_elapsed_seconds: float
    slo_p95_seconds: float
    peak_memory_mb: float
    total_errors: int


class SignedURLBuilder:
    def __init__(self, *, signing_key: str) -> None:
        self.signing_key = signing_key.encode("utf-8")

    def build(self, path: Path, *, expires_in_seconds: int) -> str:
        normalized = str(path).encode("utf-8")
        digest = sha256(self.signing_key + normalized + str(expires_in_seconds).encode("utf-8")).hexdigest()
        return f"https://download.internal/{digest}?path={path}&expires={expires_in_seconds}"


class ReadinessOrchestrator:
    """Implement Phase-9 UAT & readiness automation."""

    def __init__(
        self,
        *,
        output_root: Path,
        docs_root: Path,
        env_config: EnvironmentConfig,
        metrics: ReadinessMetrics,
        clock: Clock,
        logger: JSONLogger,
        retry_policy_factory: Callable[[str], RetryPolicy],
        year_provider: AcademicYearProvider,
    ) -> None:
        self.output_root = output_root
        self.docs_root = docs_root
        self.env_config = env_config
        self.metrics = metrics
        self.clock = clock
        self.logger = logger
        self.retry_policy_factory = retry_policy_factory
        self.year_provider = year_provider
        self._log_path = output_root / "phase9_readiness.log"
        self._ensure_dirs()
        self._configure_json_logging()
        self._signed_url = SignedURLBuilder(signing_key=env_config.tokens.download_signing)

    def _ensure_dirs(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.docs_root.mkdir(parents=True, exist_ok=True)

    def _configure_json_logging(self) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._log_path.exists():
            self._log_path.write_text("", encoding="utf-8")

    def _log(self, correlation_id: str, event: str, **fields: Any) -> None:
        payload = {"correlation_id": correlation_id, **fields}
        self.logger.bind(correlation_id).info(event, **payload)
        record = {"event": event, **payload}
        with self._log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    def _write_csv(self, path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        headers = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=headers, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: self._excel_safe(value, key) for key, value in row.items()})

    def _excel_safe(self, value: Any, column: str) -> Any:
        if value is None:
            return ""
        text = _canonical_text(value)
        if column in _SENSITIVE_COLUMNS:
            return f"'{text}"
        if text.startswith(_FORMULA_PREFIXES):
            return f"'{text}"
        return text

    def _build_traceability_rows(
        self,
        *,
        scenarios: Sequence[UATScenario],
        checklist: Sequence[AcceptanceChecklistItem],
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        evidence_map: MutableMapping[str, list[str]] = defaultdict(list)
        for item in checklist:
            if item.evidence_path:
                evidence_map[item.id].append(item.evidence_path)
        rows: list[dict[str, Any]] = []
        for scenario in scenarios:
            for item_id in scenario.checklist_ids:
                rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "title": scenario.title,
                        "requirement_id": item_id,
                        "spec_reference": next(
                            (item.spec_reference for item in checklist if item.id == item_id),
                            "",
                        ),
                        "evidence": " | ".join(evidence_map.get(item_id, [])),
                        "criticality": scenario.criticality,
                        "correlation_id": correlation_id,
                    }
                )
        return rows

    def generate_uat_plan(
        self,
        *,
        checklist: Sequence[AcceptanceChecklistItem],
        scenarios: Sequence[UATScenario],
        correlation_id: str,
    ) -> list[dict[str, Any]]:
        rows = self._build_traceability_rows(scenarios=scenarios, checklist=checklist, correlation_id=correlation_id)
        uat_plan = [
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "description": scenario.description,
                "criticality": scenario.criticality,
                "checklist": [item for item in rows if item["scenario_id"] == scenario.scenario_id],
                "owner_phone": scenario.owner_phone,
                "registration_center": scenario.registration_center,
                "registration_status": scenario.registration_status,
                "counter_id": scenario.counter_id,
                "academic_year_code": self.year_provider.code_for(scenario.academic_year),
                "correlation_id": correlation_id,
            }
            for scenario in scenarios
        ]
        self._write_json(self.output_root / "uat_plan.json", uat_plan)
        self._write_csv(
            self.output_root / "uat_plan.csv",
            [
                {
                    "scenario_id": entry["scenario_id"],
                    "title": entry["title"],
                    "criticality": entry["criticality"],
                    "registration_center": entry["registration_center"],
                    "registration_status": entry["registration_status"],
                    "counter_id": entry["counter_id"],
                    "academic_year_code": entry["academic_year_code"],
                    "owner_phone": entry["owner_phone"],
                }
                for entry in uat_plan
            ],
        )
        self._write_csv(self.docs_root / "traceability_matrix.csv", rows)
        self.metrics.uat_plan_runs.labels(outcome="success", namespace=self.env_config.namespace).inc()
        self._log(correlation_id, "uat.plan.generated", count=len(uat_plan))
        return uat_plan

    def run_pilot(
        self,
        *,
        dataset: Iterable[bytes] | Callable[[], Iterable[bytes]],
        upload: Callable[[Iterable[bytes]], dict[str, Any]],
        validate: Callable[[], dict[str, Any]],
        activate: Callable[[], dict[str, Any]],
        export: Callable[[], dict[str, Any]],
        correlation_id: str,
    ) -> PilotReport:
        namespace = self.env_config.namespace
        retry_upload = self.retry_policy_factory("upload")
        retry_validate = self.retry_policy_factory("validate")
        retry_activate = self.retry_policy_factory("activate")
        retry_export = self.retry_policy_factory("export")

        meter = StreamingPilotMeter(
            source=dataset,
            clock=self.clock,
            tmp_root=self.output_root / "tmp",
        )
        stream_stats = meter.prepare()
        try:
            upload_result, upload_duration = self.clock.measure(
                lambda: retry_upload.run(
                    lambda: upload(meter.stream()),
                    method="POST",
                    operation="upload",
                    correlation_id=correlation_id,
                )
            )
            validate_result, validate_duration = self.clock.measure(
                lambda: retry_validate.run(
                    validate,
                    method="POST",
                    operation="validate",
                    correlation_id=correlation_id,
                )
            )
            activate_result, activate_duration = self.clock.measure(
                lambda: retry_activate.run(
                    activate,
                    method="POST",
                    operation="activate",
                    correlation_id=correlation_id,
                )
            )
            export_result, export_duration = self.clock.measure(
                lambda: retry_export.run(
                    export,
                    method="GET",
                    operation="export",
                    correlation_id=correlation_id,
                    fail_open_result=lambda exc: {"status": "fail-open", "error": str(exc)},
                )
            )
        finally:
            meter.cleanup()
        self.metrics.observe_duration(stage="pilot.upload", seconds=upload_duration)
        self.metrics.observe_duration(stage="pilot.validate", seconds=validate_duration)
        self.metrics.observe_duration(stage="pilot.activate", seconds=activate_duration)
        self.metrics.observe_duration(stage="pilot.export", seconds=export_duration)

        stages = [
            PilotStageResult(
                name="upload",
                duration_seconds=float(upload_result.get("duration", 0.0)),
                memory_mb=float(upload_result.get("memory", 0.0)),
                errors=list(upload_result.get("errors", [])),
            ),
            PilotStageResult(
                name="validate",
                duration_seconds=float(validate_result.get("duration", 0.0)),
                memory_mb=float(validate_result.get("memory", 0.0)),
                errors=list(validate_result.get("errors", [])),
            ),
            PilotStageResult(
                name="activate",
                duration_seconds=float(activate_result.get("duration", 0.0)),
                memory_mb=float(activate_result.get("memory", 0.0)),
                errors=list(activate_result.get("errors", [])),
            ),
            PilotStageResult(
                name="export",
                duration_seconds=float(export_result.get("duration", 0.0)),
                memory_mb=float(export_result.get("memory", 0.0)),
                errors=list(export_result.get("errors", [])),
            ),
        ]
        total_samples = [stage.duration_seconds for stage in stages if stage.duration_seconds]
        slo_p95 = 0.0
        if total_samples:
            sorted_samples = sorted(total_samples)
            index = int(len(sorted_samples) * 0.95) - 1
            index = max(0, min(index, len(sorted_samples) - 1))
            slo_p95 = sorted_samples[index]
        peak_memory = max((stage.memory_mb for stage in stages), default=0.0)
        total_errors = sum(len(stage.errors) for stage in stages)
        pilot_run_id = blake2b(
            f"{correlation_id}|{self.clock.isoformat()}|{namespace}".encode("utf-8"), digest_size=16
        ).hexdigest()
        report = PilotReport(
            run_id=pilot_run_id,
            correlation_id=correlation_id,
            stages=stages,
            row_count=stream_stats.rows,
            dataset_bytes=stream_stats.bytes,
            dataset_checksum=stream_stats.checksum,
            stream_elapsed_seconds=stream_stats.elapsed_seconds,
            slo_p95_seconds=slo_p95,
            peak_memory_mb=peak_memory,
            total_errors=total_errors,
        )
        self._write_json(self.output_root / "pilot_report.json", self._pilot_report_payload(report))
        self.metrics.pilot_runs.labels(outcome="success", namespace=namespace).inc()
        self._log(
            correlation_id,
            "uat.pilot.completed",
            run_id=report.run_id,
            slo_p95=report.slo_p95_seconds,
            peak_memory=report.peak_memory_mb,
            errors=report.total_errors,
            rows=report.row_count,
            dataset_bytes=report.dataset_bytes,
            checksum=report.dataset_checksum,
        )
        return report

    def _pilot_report_payload(self, report: PilotReport) -> dict[str, Any]:
        return {
            "run_id": report.run_id,
            "correlation_id": report.correlation_id,
            "stages": [
                {
                    "name": stage.name,
                    "duration_seconds": stage.duration_seconds,
                    "memory_mb": stage.memory_mb,
                    "errors": stage.errors,
                }
                for stage in report.stages
            ],
            "row_count": report.row_count,
            "dataset_bytes": report.dataset_bytes,
            "dataset_checksum": report.dataset_checksum,
            "stream_elapsed_seconds": report.stream_elapsed_seconds,
            "slo_p95_seconds": report.slo_p95_seconds,
            "peak_memory_mb": report.peak_memory_mb,
            "total_errors": report.total_errors,
        }

    def execute_blue_green(
        self,
        *,
        prepare: Callable[[], dict[str, Any]],
        switch: Callable[[str], dict[str, Any]],
        verify: Callable[[str], dict[str, Any]],
        rollback: Callable[[str], dict[str, Any]],
        correlation_id: str,
    ) -> dict[str, Any]:
        namespace = self.env_config.namespace
        deployment, prepare_duration = self.clock.measure(prepare)
        self.metrics.observe_duration(stage="bluegreen.prepare", seconds=prepare_duration)
        new_slot = deployment["slot"]
        verify_result, verify_duration = self.clock.measure(lambda: verify(new_slot))
        self.metrics.observe_duration(stage="bluegreen.verify", seconds=verify_duration)
        if verify_result.get("ready") is not True:
            _, rollback_duration = self.clock.measure(lambda: rollback(new_slot))
            self.metrics.observe_duration(stage="bluegreen.rollback", seconds=rollback_duration)
            self.metrics.bluegreen_rollbacks.labels(outcome="rollback", namespace=namespace).inc()
            raise RuntimeError("آماده‌سازی محیط آبی/سبز شکست خورد.")
        switch_result, switch_duration = self.clock.measure(lambda: switch(new_slot))
        self.metrics.observe_duration(stage="bluegreen.switch", seconds=switch_duration)
        evidence = {
            "slot": new_slot,
            "switched": switch_result.get("switched", False),
            "readiness_p95_ms": verify_result.get("p95_ms", 0.0),
            "error_rate": verify_result.get("errors", 0),
            "correlation_id": correlation_id,
        }
        if evidence["readiness_p95_ms"] >= 200:
            _, rollback_duration = self.clock.measure(lambda: rollback(new_slot))
            self.metrics.observe_duration(stage="bluegreen.rollback", seconds=rollback_duration)
            self.metrics.bluegreen_rollbacks.labels(outcome="rollback", namespace=namespace).inc()
            raise RuntimeError("درگاه آماده‌سازی کند است.")
        self.metrics.bluegreen_rollbacks.labels(outcome="success", namespace=namespace).inc()
        self._write_json(self.output_root / "bluegreen_report.json", evidence)
        self._log(correlation_id, "uat.bluegreen.switched", slot=new_slot, readiness_p95_ms=evidence["readiness_p95_ms"])
        return evidence

    def verify_backup_restore(
        self,
        *,
        create_backup: Callable[[], Path],
        restore_backup: Callable[[Path], dict[str, Any]],
        retention_validator: RetentionValidator,
        correlation_id: str,
    ) -> dict[str, Any]:
        namespace = self.env_config.namespace
        backup_path, backup_duration = self.clock.measure(create_backup)
        self.metrics.observe_duration(stage="backup.create", seconds=backup_duration)
        digest = sha256()
        with backup_path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(65536), b""):
                digest.update(chunk)
        checksum = digest.hexdigest()
        restore_result, restore_duration = self.clock.measure(lambda: restore_backup(backup_path))
        self.metrics.observe_duration(stage="backup.restore", seconds=restore_duration)
        if restore_result.get("checksum") != checksum:
            self.metrics.backup_restore_runs.labels(
                stage="restore", outcome="checksum_mismatch", namespace=namespace
            ).inc()
            raise RuntimeError("بررسی هش بازیابی شکست خورد.")
        retention_result, retention_duration = self.clock.measure(retention_validator.run)
        self.metrics.observe_duration(stage="backup.retention", seconds=retention_duration)
        payload = {
            "backup_path": str(backup_path),
            "checksum": checksum,
            "restore": restore_result,
            "retention": retention_result,
            "correlation_id": correlation_id,
        }
        self.metrics.backup_restore_runs.labels(stage="backup", outcome="success", namespace=namespace).inc()
        self.metrics.backup_restore_runs.labels(stage="restore", outcome="success", namespace=namespace).inc()
        self.metrics.backup_restore_runs.labels(stage="retention", outcome="success", namespace=namespace).inc()
        self._write_json(self.output_root / "backup_restore_report.json", payload)
        self._log(correlation_id, "uat.backup.completed", checksum=checksum)
        return payload

    def build_go_no_go(self, *, correlation_id: str) -> Path:
        uat_plan = json.loads((self.output_root / "uat_plan.json").read_text(encoding="utf-8"))
        pilot = json.loads((self.output_root / "pilot_report.json").read_text(encoding="utf-8"))
        bluegreen = json.loads((self.output_root / "bluegreen_report.json").read_text(encoding="utf-8"))
        backup = json.loads((self.output_root / "backup_restore_report.json").read_text(encoding="utf-8"))
        lines = [
            "# بسته تصمیم‌گیری Go/No-Go",
            "",
            f"- شناسه همبستگی: `{correlation_id}`",
            f"- سناریوهای UAT: {len(uat_plan)}",
            f"- اجرای آزمایشی: SLO p95 = {pilot['slo_p95_seconds']:.3f}s، حافظه اوج = {pilot['peak_memory_mb']:.1f}MB",
            f"- Blue/Green: اسلات فعال = {bluegreen['slot']}",
            f"- پشتیبان: مسیر = {backup['backup_path']}",
            "",
            "## لینک‌های امضاشده",
            f"- گزارش آزمایشی: {self._signed_url.build(self.output_root / 'pilot_report.json', expires_in_seconds=3600)}",
            f"- گزارش بکاپ: {self._signed_url.build(self.output_root / 'backup_restore_report.json', expires_in_seconds=3600)}",
        ]
        destination = self.docs_root / "RUNBOOK_addendum.md"
        destination.write_text("\n".join(lines), encoding="utf-8")
        return destination

    def stream_dataset(self, path: Path, *, chunk_size: int = 65536) -> Iterator[bytes]:
        with path.open("rb") as fp:
            while True:
                chunk = fp.read(chunk_size)
                if not chunk:
                    break
                yield chunk


__all__ = [
    "EnvironmentConfig",
    "TokenConfig",
    "AcceptanceChecklistItem",
    "UATScenario",
    "ReadinessOrchestrator",
    "PilotReport",
    "PilotStageResult",
]
