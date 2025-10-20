"""Unified Typer CLI for developer ergonomics and production tasks."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tracemalloc
import time
import typing as t
import warnings
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent


def _bootstrap_paths() -> None:
    """Ensure repository root and ``src`` are importable without PYTHONPATH tweaks."""

    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    for candidate in (src, root):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
    root_tools = root / "tools"
    existing = sys.modules.get("tools")
    if (
        not existing
        or getattr(existing, "__file__", "").startswith(str(src))
        or getattr(existing, "__path__", None) == [str(src / "tools")]
    ) and (root_tools / "__init__.py").exists():
        spec = importlib.util.spec_from_file_location("tools", root_tools / "__init__.py")
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            module.__path__ = [str(root_tools)]  # type: ignore[attr-defined]
            spec.loader.exec_module(module)
            sys.modules["tools"] = module


_bootstrap_paths()

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

warnings.filterwarnings(
    "ignore",
    message=".*BaseCommand.*is deprecated.*",
    category=DeprecationWarning,
)

import typer
from fastapi import Request
from fastapi.testclient import TestClient

from sma.export.excel_writer import ExportWriter
from observability.metrics import PerformanceBudgets, PerformanceMonitor, create_metrics
from sma.phase6_import_to_sabt.app.app_factory import create_application
from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore
from sma.phase6_import_to_sabt.app.timing import DeterministicTimer
from sma.phase6_import_to_sabt.obs.metrics import build_metrics
from sma.phase6_import_to_sabt.security.config import SigningKeyDefinition
from sma.security.signing import KeyRingSigner, keyring_from_definitions, deterministic_secret

app = typer.Typer(help="Student Mentor Allocation System CLI")

DEFAULT_TOKENS = [
    {"value": "cli-admin-token-1234567890", "role": "ADMIN"},
    {"value": "cli-metrics-token-1234567890", "role": "METRICS_RO"},
]
DEFAULT_KEYS = [
    {"kid": "cli0", "secret": deterministic_secret("cli0"), "state": "retired"},
    {"kid": "cli1", "secret": deterministic_secret("cli1"), "state": "active"},
]


def _ensure_env(namespace: str) -> AppConfig:
    os.environ.setdefault("TOKENS", json.dumps(DEFAULT_TOKENS, ensure_ascii=False))
    os.environ.setdefault("DOWNLOAD_SIGNING_KEYS", json.dumps(DEFAULT_KEYS, ensure_ascii=False))
    config_payload = {
        "redis": {"dsn": "redis://localhost:6379/0", "namespace": f"{namespace}", "operation_timeout": 0.2},
        "database": {"dsn": "postgresql://localhost/{namespace}", "statement_timeout_ms": 500},
        "auth": {
            "metrics_token": DEFAULT_TOKENS[1]["value"],
            "service_token": DEFAULT_TOKENS[0]["value"],
        },
        "timezone": "Asia/Tehran",
        "enable_debug_logs": False,
        "enable_diagnostics": False,
    }
    return AppConfig.model_validate(config_payload)


def _build_test_app(namespace: str) -> TestClient:
    config = _ensure_env(namespace)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc))
    metrics = build_metrics(f"{namespace}_metrics")
    timer = DeterministicTimer([0.01, 0.02, 0.03])
    rate_store = InMemoryKeyValueStore(f"{namespace}:rate", clock)
    idem_store = InMemoryKeyValueStore(f"{namespace}:idem", clock)
    fastapi_app = create_application(
        config,
        clock=clock,
        metrics=metrics,
        timer=timer,
        rate_limit_store=rate_store,
        idempotency_store=idem_store,
    )

    @fastapi_app.post("/__lint")
    async def _lint_echo(request: Request) -> dict[str, t.Any]:  # pragma: no cover - docs helper
        return {"path": request.url.path}

    return TestClient(fastapi_app)


def _resolve_ref(schema: t.Any, components: dict[str, t.Any]) -> dict[str, t.Any]:
    if not isinstance(schema, dict):
        return {}
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"].split("/")[-1]
    resolved = components.get("schemas", {}).get(ref)
    return resolved or {}


def _example_from_schema(
    schema: dict[str, t.Any], components: dict[str, t.Any], depth: int = 0
) -> t.Any:
    if depth > 6:
        return "…"
    schema = _resolve_ref(schema, components)
    if not schema:
        return "نمونه"
    if "example" in schema:
        return schema["example"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    schema_type = schema.get("type")
    if schema_type == "object":
        props = schema.get("properties", {})
        example: dict[str, t.Any] = {}
        for key, value in sorted(props.items()):
            example[key] = _example_from_schema(value, components, depth + 1)
        additional = schema.get("additionalProperties")
        if not example and additional:
            example["نمونه"] = _example_from_schema(additional, components, depth + 1)
        return example
    if schema_type == "array":
        items = schema.get("items", {})
        return [_example_from_schema(items, components, depth + 1)]
    if schema_type == "integer":
        return schema.get("minimum", 1)
    if schema_type == "number":
        return schema.get("minimum", 1.0)
    if schema_type == "boolean":
        return True
    if schema.get("format") == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    if schema.get("format") == "date-time":
        return "2024-01-01T00:00:00Z"
    if schema.get("format") == "date":
        return "2024-01-01"
    if schema_type == "string":
        pattern = schema.get("pattern")
        if pattern:
            return pattern
        return "نمونه"
    return "نمونه"


def _pick_status(responses: dict[str, t.Any]) -> tuple[str, dict[str, t.Any]] | tuple[None, None]:
    for status_code in ("200", "201", "202", "204"):
        if status_code in responses:
            return status_code, responses[status_code]
    if responses:
        key = sorted(responses)[0]
        return key, responses[key]
    return None, None


def _extract_json_content(payload: dict[str, t.Any]) -> dict[str, t.Any] | None:
    content = payload.get("content", {}) if payload else {}
    return content.get("application/json")


def generate_endpoint_markdown(schema: dict[str, t.Any]) -> str:
    components = schema.get("components", {})
    lines: list[str] = [
        "# API Endpoints",
        "",
        "این مستند از OpenAPI تولید شده است و نمونه‌ها قابل اجرا هستند.",
    ]
    for path, methods in sorted(schema.get("paths", {}).items()):
        for method, info in sorted(methods.items()):
            summary = info.get("summary", "")
            lines.append(f"## `{method.upper()} {path}`")
            if summary:
                lines.append(summary)
            command = [
                "curl",
                f"-X {method.upper()}",
                f"http://localhost:8000{path}",
                f"-H 'Authorization: Bearer {DEFAULT_TOKENS[0]['value']}'",
            ]
            if path == "/metrics":
                command.append(
                    f"-H 'X-Metrics-Token: {DEFAULT_TOKENS[1]['value']}'"
                )
            request_example: t.Any | None = None
            request_payload = _extract_json_content(info.get("requestBody", {}))
            if request_payload:
                request_example = _example_from_schema(
                    request_payload.get("schema", {}), components
                )
            elif method.upper() in {"POST", "PUT", "PATCH"}:
                request_example = {"نمونه": "نمونه"}
            if request_example is not None:
                command.append("-H 'Content-Type: application/json'")
                command.append(f"-d '{json.dumps(request_example, ensure_ascii=False)}'")
            lines.append("```")
            lines.append(" ".join(command))
            lines.append("```")
            if request_example is not None:
                lines.append("**Request Example**")
                lines.append("```json")
                lines.append(json.dumps(request_example, ensure_ascii=False, indent=2, sort_keys=True))
                lines.append("```")
            status, response_info = _pick_status(info.get("responses", {}))
            if response_info:
                json_content = _extract_json_content(response_info)
                if json_content:
                    response_example = _example_from_schema(
                        json_content.get("schema", {}), components
                    )
                    status_label = status or "default"
                    lines.append(f"**Response Example ({status_label})**")
                    lines.append("```json")
                    lines.append(
                        json.dumps(
                            response_example,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                    )
                    lines.append("```")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_operations_markdown(budgets: PerformanceBudgets) -> str:
    return dedent(
        f"""
        # عملیات و پایداری

        ## چرخش کلید دانلود
        - از دستور `smasm rotate-keys --new-kid NEW1` استفاده کنید.
        - پس از چرخش، کلید قبلی به حالت بازنشسته تغییر می‌کند اما تا اتمام TTL معتبر است.

        ## بودجه‌های عملکردی
        - p95 صادرات: {budgets.exporter_p95_seconds * 1000:.0f} میلی‌ثانیه
        - p95 امضا: {budgets.signing_p95_seconds * 1000:.0f} میلی‌ثانیه
        - حافظه بیشینه: {budgets.memory_peak_mb:.0f} مگابایت

        ## کنترل سلامت و مشاهد‌پذیری
        - مسیر `/metrics` تنها با هدر `X-Metrics-Token` معتبر است.
        - شمارنده‌های تکرار (`retry_attempts_total`) و شکست تکرار (`retry_exhausted_total`) در Prometheus ثبت می‌شوند.
        """
    ).strip() + "\n"


@app.command()
def init() -> None:
    """Create deterministic workspace directories."""

    for directory in ("artifacts", "logs", "reports", "docs"):
        Path(directory).mkdir(parents=True, exist_ok=True)
    typer.echo("فضای کاری آماده شد (artifacts/logs/reports/docs).")


@app.command()
def migrate(target: str = typer.Option("head", help="Alembic revision target")) -> None:
    """Run Alembic migrations in deterministic mode."""

    env = os.environ.copy()
    subprocess.run(["alembic", "upgrade", target], check=True, env=env)
    typer.echo(f"مهاجرت پایگاه‌داده تا {target} با موفقیت انجام شد.")


@app.command()
def run(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Run the FastAPI application via uvicorn."""

    import uvicorn

    typer.echo(f"اجرای سرویس روی http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)


@app.command()
def perf(rows: int = typer.Option(2000, min=10, help="Row count for the exporter benchmark")) -> None:
    """Exercise exporter and signing paths against performance budgets."""

    budgets = PerformanceBudgets()
    metrics = create_metrics("cli_perf")
    monitor = PerformanceMonitor(metrics=metrics, budgets=budgets)
    writer = ExportWriter(sensitive_columns=["national_id", "counter", "mobile"])

    sample_row = {
        "national_id": "1234567890",
        "counter": "1403730001",
        "first_name": "یاسمین",
        "last_name": "کاظمی",
        "gender": "1",
        "mobile": "09121234567",
        "reg_center": "1",
        "reg_status": "3",
        "group_code": "200",
        "student_type": "1",
        "school_code": "123456",
        "mentor_id": "998877",
        "mentor_name": "استاد نمونه",
        "mentor_mobile": "09129876543",
        "allocation_date": "2024-01-01T00:00:00Z",
        "year_code": "1402",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        csv_path = output_dir / "export.csv"
        tracemalloc.start()
        start = time.perf_counter()
        result = writer.write_csv((sample_row for _ in range(rows)), path_factory=lambda _: csv_path)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        duration = time.perf_counter() - start
        monitor.record_export(duration=duration, memory_bytes=peak)
        typer.echo(f"CSV rows={result.total_rows} duration={duration:.4f}s peak={peak/1024/1024:.2f}MB")

        key_defs = [SigningKeyDefinition(item["kid"], item["secret"], item.get("state", "active")) for item in DEFAULT_KEYS]
        signer = KeyRingSigner(keyring_from_definitions(key_defs), clock=FixedClock(datetime(2024, 1, 1, tzinfo=timezone.utc)), default_ttl_seconds=900)
        for idx in range(10):
            tracemalloc.start()
            start = time.perf_counter()
            envelope = signer.issue(f"/download/{idx}")
            signer.verify(envelope)
            _, peak_sign = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            duration_sign = time.perf_counter() - start
            monitor.record_signing(duration=duration_sign, memory_bytes=peak_sign)

    summary = monitor.ensure_within_budget()
    typer.echo(dedent(
        f"""
        نتیجه بودجه عملکرد:
          p95 صادرات: {summary['exporter_p95']:.4f}s
          p95 امضا: {summary['signing_p95']:.4f}s
          حافظه بیشینه: {summary['memory_peak_mb']:.2f}MB
        """
    ).strip())


@app.command()
def docs(
    endpoints_path: Path = typer.Option(Path("docs/ENDPOINTS.md"), help="Output markdown for endpoints"),
    operations_path: Path = typer.Option(Path("docs/OPERATIONS.md"), help="Output markdown for operations"),
) -> None:
    """Generate Markdown documentation for endpoints and operations."""

    with _build_test_app("docs") as client:
        schema = client.app.openapi()
    endpoints_markdown = generate_endpoint_markdown(schema)
    endpoints_path.parent.mkdir(parents=True, exist_ok=True)
    endpoints_path.write_text(endpoints_markdown, encoding="utf-8")

    budgets = PerformanceBudgets()
    operations_markdown = generate_operations_markdown(budgets)
    operations_path.write_text(operations_markdown, encoding="utf-8")
    typer.echo(f"مستندات در {endpoints_path} و {operations_path} تولید شد.")


@app.command("rotate-keys")
def rotate_keys(
    new_kid: str = typer.Option(..., help="شناسه کلید جدید"),
    output: Path = typer.Option(Path("download_keys.json"), help="مسیر خروجی"),
    seed: t.Optional[str] = typer.Option(None, help="بذر اختیاری برای تولید راز"),
) -> None:
    """Rotate the download key set and persist the new configuration."""

    current = DEFAULT_KEYS
    if output.exists():
        current = json.loads(output.read_text(encoding="utf-8"))
    definitions = [SigningKeyDefinition(item["kid"], item["secret"], item.get("state", "active")) for item in current]
    ring = keyring_from_definitions(definitions)
    secret = deterministic_secret(seed or new_kid)
    updated = ring.rotate(kid=new_kid, secret=secret)
    serialized = [
        {"kid": key.kid, "secret": key.secret, "state": key.state}
        for key in updated.verification_keys()
    ]
    output.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo("کلید جدید با موفقیت فعال شد و نسخه‌های قبلی در حالت بازنشسته باقی ماندند.")


@app.command()
def lint() -> None:
    """Run ruff and mypy checks."""

    subprocess.run(["ruff", "check", "src", "tests"], check=True)
    subprocess.run(["mypy", "src"], check=True)


@app.command()
def test(pytest_args: t.List[str] = typer.Argument(None)) -> None:
    """Run the deterministic pytest suite with plugin autoload disabled."""

    args = ["-q"] + (pytest_args or [])
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    subprocess.run(["pytest", "-p", "pytest_asyncio", *args], check=True, env=env)


def main() -> None:
    """Entry point for console scripts without PYTHONPATH fiddling."""

    app()


@app.command()
def clean() -> None:
    """Remove build/test artifacts deterministically."""

    for path in (".pytest_cache", "artifacts", "logs", "reports", "dist", "build"):
        if Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
    typer.echo("پاکسازی انجام شد.")


if __name__ == "__main__":
    main()

