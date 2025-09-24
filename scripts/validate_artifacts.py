from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

import yaml

from src.phase2_counter_service.validation import COUNTER_PATTERN, COUNTER_PREFIX

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
SPEC_MATRIX = REPORTS_DIR / "spec_matrix.md"


def _load_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> None:
    yaml.safe_load(path.read_text(encoding="utf-8"))


def _iter_paths(directory: Path, patterns: Iterable[str]) -> Iterable[Path]:
    for pattern in patterns:
        yield from directory.glob(pattern)


def validate_monitoring_assets() -> List[str]:
    errors: List[str] = []
    grafana_dir = ROOT / "monitoring" / "grafana" / "dashboards"
    for path in grafana_dir.glob("*.json"):
        try:
            _load_json(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid Grafana JSON: {path.name} ({exc})")
    prom_dir = ROOT / "monitoring" / "prometheus"
    for path in _iter_paths(prom_dir, ("*.yml", "*.yaml")):
        try:
            _load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid Prometheus YAML: {path.name} ({exc})")
    return errors


def generate_spec_matrix() -> str:
    lines = [
        "# Spec Matrix",
        "",
        "| ویژگی | مقدار |",
        "| --- | --- |",
        f"| الگوی شمارنده | `{COUNTER_PATTERN.pattern}` |",
        f"| نگاشت جنسیت→پیشوند | `{COUNTER_PREFIX}` |",
        "| پوشش تست مورد انتظار | `>=95%` |",
        "| ابزارهای CI | `pytest --cov`, `mypy --strict`, `bandit`, `post_migration_checks` |",
    ]
    return "\n".join(lines) + "\n"


def ensure_spec_matrix() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    content = generate_spec_matrix()
    existing = SPEC_MATRIX.read_text(encoding="utf-8") if SPEC_MATRIX.exists() else ""
    if existing != content:
        SPEC_MATRIX.write_text(content, encoding="utf-8")


def main() -> int:
    ensure_spec_matrix()
    errors = validate_monitoring_assets()
    if errors:
        for error in errors:
            print(f"❌ {error}")
        return 1
    print("✅ Artifacts validated")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
