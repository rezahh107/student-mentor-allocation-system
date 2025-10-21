from __future__ import annotations

import os
import pathlib
import re

import importlib

repo_root = pathlib.Path(__file__).resolve().parents[2]

try:
    import pytest
except ModuleNotFoundError:
    from scripts.ci.ensure_ci_ready import CiReadyGuard

    CiReadyGuard(repo_root, ["pytest", "pytest_asyncio"], persian=True).run()
    raise

AGENTS_EVIDENCE = "AGENTS.md::3 Absolute Guardrails"


@pytest.mark.evidence(AGENTS_EVIDENCE)
def test_no_package_shadowing() -> None:
    critical = {"fastapi", "sqlalchemy", "pytest", "pydantic", "requests", "numpy", "pandas", "uvicorn", "redis", "fakeredis"}
    src_root = pathlib.Path(__file__).resolve().parents[2] / "src"
    present = sorted(name for name in critical if (src_root / name).exists())
    assert not present, f"خطا: پوشه‌های ممنوع هنوز موجود هستند: {present}"


@pytest.mark.evidence("AGENTS.md::1 Determinism")
def test_fastapi_from_site_packages() -> None:
    module = importlib.import_module("fastapi")
    module_path = pathlib.Path(module.__file__ or "")
    normalized = module_path.as_posix()
    assert "site-packages" in normalized or "dist-packages" in normalized, f"FastAPI path اشتباه است: {normalized}"


@pytest.mark.evidence("AGENTS.md::8 Testing & CI Gates")
def test_no_legacy_src_imports_left() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    pattern = os.environ.get("SMA_IMPORT_PATTERN", r"\b(import|from)\s+src\.")
    offenders: list[str] = []
    for path in repo_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(pattern, text):
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"ایمپورت‌های src باقی مانده‌اند: {offenders}"
