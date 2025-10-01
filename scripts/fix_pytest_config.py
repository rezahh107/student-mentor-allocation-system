#!/usr/bin/env python3
"""اسکریپت اصلاح خودکار پیکربندی pytest با error handling کامل."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import List

_CONFIG_FILES: List[str] = [
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
    ".pytest.ini",
]


def fix_pytest_config() -> bool:
    """اصلاح پیکربندی pytest در فایل‌های مختلف."""
    fixed_files: list[str] = []
    errors: list[str] = []

    for config_file in _CONFIG_FILES:
        path = Path(config_file)
        if not path.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
            original_content = content

            patterns_to_remove = [
                r"^\s*asyncio_default_fixture_loop_scope\s*=.*$",
                r"^\s*asyncio_default_fixture_loop_scope\s*$",
                r"\n\s*\n\s*\n",
            ]

            for pattern in patterns_to_remove:
                content = re.sub(pattern, "\n\n", content, flags=re.MULTILINE)

            if config_file == "pyproject.toml":
                content = fix_pyproject_toml(content)
            elif config_file in {"pytest.ini", ".pytest.ini"}:
                content = fix_pytest_ini(content)
            elif config_file == "setup.cfg":
                content = fix_setup_cfg(content)

            if content != original_content:
                backup_path = path.with_suffix(path.suffix + ".backup")
                backup_path.write_text(original_content, encoding="utf-8")
                path.write_text(content, encoding="utf-8")
                fixed_files.append(config_file)
                print(f"✅ پیکربندی {config_file} به‌روزرسانی شد (بکاپ: {backup_path.name})")
            else:
                print(f"ℹ️  {config_file} نیازی به تغییر ندارد")

        except Exception as exc:  # noqa: BLE001
            error_msg = f"❌ خطا در پردازش {config_file}: {exc}"
            print(error_msg, file=sys.stderr)
            errors.append(error_msg)

    if fixed_files:
        print(f"\n✅ {len(fixed_files)} فایل اصلاح شد: {', '.join(fixed_files)}")
    else:
        print("\nℹ️  هیچ فایلی نیاز به اصلاح نداشت")

    if errors:
        print(f"\n⚠️  {len(errors)} خطا رخ داد:")
        for error in errors:
            print(f"  - {error}")
        return False

    return True


def fix_pyproject_toml(content: str) -> str:
    """اصلاح خاص pyproject.toml."""
    if "[tool.pytest.ini_options]" not in content:
        pytest_config = (
            "\n[tool.pytest.ini_options]\n"
            'asyncio_mode = "auto"\n'
            "strict_markers = true\n"
            "strict_config = true\n"
            'testpaths = ["tests", "test"]\n'
            'python_files = ["test_*.py", "*_test.py"]\n'
            'addopts = ["--strict-markers", "--tb=short", "-ra"]\n'
            "markers = [\n"
            '    "slow: marks tests as slow",\n'
            '    "integration: marks tests as integration tests",\n'
            '    "unit: marks tests as unit tests",\n'
            "]\n"
        )
        return content + pytest_config

    if "asyncio_mode" not in content:
        content = re.sub(
            r"(\[tool\.pytest\.ini_options\])",
            r'\1\nasyncio_mode = "auto"',
            content,
        )

    return content


def fix_pytest_ini(content: str) -> str:
    """اصلاح خاص pytest.ini."""
    if "[pytest]" not in content:
        pytest_config = (
            "[pytest]\n"
            "asyncio_mode = auto\n"
            "strict_markers = true\n"
            "testpaths = tests test\n"
            "python_files = test_*.py *_test.py\n"
            "addopts = --strict-markers --tb=short -ra\n"
            "markers =\n"
            "    slow: marks tests as slow\n"
            "    integration: marks tests as integration tests\n"
            "    unit: marks tests as unit tests\n"
        )
        return pytest_config + content

    if "asyncio_mode" not in content:
        content = re.sub(
            r"(\[pytest\])",
            r"\1\nasyncio_mode = auto",
            content,
        )

    return content


def fix_setup_cfg(content: str) -> str:
    """اصلاح خاص setup.cfg."""
    if "[tool:pytest]" not in content:
        pytest_config = (
            "\n[tool:pytest]\n"
            "asyncio_mode = auto\n"
            "strict_markers = true\n"
            "testpaths = tests test\n"
            "python_files = test_*.py *_test.py\n"
            "addopts = --strict-markers --tb=short -ra\n"
        )
        return content + pytest_config

    if "asyncio_mode" not in content:
        content = re.sub(
            r"(\[tool:pytest\])",
            r"\1\nasyncio_mode = auto",
            content,
        )

    return content


def validate_pytest_config() -> bool:
    """اعتبارسنجی پیکربندی pytest."""
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "--collect-only", "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"❌ خطا در اعتبارسنجی: {exc}")
        return False

    if result.returncode == 0:
        print("✅ پیکربندی pytest معتبر است")
        return True

    print(f"❌ خطا در پیکربندی pytest: {result.stderr}")
    return False


if __name__ == "__main__":
    print("🔧 شروع اصلاح پیکربندی pytest...")
    success = fix_pytest_config()

    if success:
        print("\n🔍 اعتبارسنجی پیکربندی...")
        validation_success = validate_pytest_config()
        sys.exit(0 if validation_success else 1)

    sys.exit(1)
