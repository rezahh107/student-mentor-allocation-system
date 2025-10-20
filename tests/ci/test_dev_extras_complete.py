from __future__ import annotations

from pathlib import Path

REQUIRED_PACKAGES = {
    "fastapi",
    "httpx",
    "prometheus-client",
    "psutil",
    "PyYAML",
    "pytest",
    "pytest-asyncio",
    "pytest-timeout",
    "pytest-xdist",
    "ruff",
    "XlsxWriter",
}


def _parse_dev_section(text: str) -> set[str]:
    packages: set[str] = set()
    in_optional = False
    collecting = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not in_optional:
            if line == "[project.optional-dependencies]":
                in_optional = True
            continue
        if not collecting:
            if line.startswith("[") and line.endswith("]") and not line.startswith("[project.optional-dependencies]"):
                break
            if line.startswith("dev") and line.endswith("["):
                collecting = True
            continue
        if line.startswith("]"):
            return packages
        if not line or line.startswith("#"):
            continue
        token = line.rstrip(",").strip('"')
        if ">=" in token:
            token = token.split(">=", 1)[0]
        elif "<" in token:
            token = token.split("<", 1)[0]
        if "[" in token:
            token = token.split("[", 1)[0]
        packages.add(token.strip())
    raise AssertionError("لیست dev به درستی پایان نیافت؛ ساختار pyproject.toml را بررسی کنید.")


def test_dev_extras_complete():
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")
    packages = _parse_dev_section(pyproject_text)
    missing = sorted(pkg for pkg in REQUIRED_PACKAGES if pkg not in packages)
    assert not missing, "وابستگی‌های dev ناقص هستند: " + ", ".join(missing)
