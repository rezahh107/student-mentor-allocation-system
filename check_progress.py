# -*- coding: utf-8 -*-
"""
check_progress.py — Auto-generated installer/resume helper for Student Mentor Allocation System

این اسکریپت وضعیت نصب/پیکربندی را بررسی می‌کند، مراحل انجام‌شده را رد می‌کند
و دقیقاً می‌گوید مرحلهٔ بعدی چیست. برای اجرا کافیست دوبار کلیک کنید.
"""

from __future__ import annotations

import os
import sys
import json
import socket
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# Added improvements
import platform
import shutil
from datetime import datetime

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT  # اگر کنار فایل‌های پروژه باشد، همین مسیر است

# بسته‌ها: (package_name, import_name)
# بر اساس requirements.txt پروژه، با نگاشت‌های لازم
REQUIRED_MODULES: List[Tuple[str, str]] = [
  ("fastapi", "fastapi"),
  ("starlette", "starlette"),
  ("uvicorn", "uvicorn"),
  ("pydantic", "pydantic"),
  ("pydantic-settings", "pydantic_settings"),
  ("python-dateutil", "dateutil"),
  ("SQLAlchemy", "sqlalchemy"),
  ("psycopg", "psycopg"),
  ("redis", "redis"),
  ("alembic", "alembic"),
  ("prometheus-client", "prometheus_client"),
  ("tenacity", "tenacity"),
  ("openpyxl", "openpyxl"),
  ("XlsxWriter", "xlsxwriter"),
  ("jdatetime", "jdatetime"),
  # tzdata: no import module needed
  ("orjson", "orjson"),
  ("jsonschema", "jsonschema"),
  ("PyYAML", "yaml"),
  ("packaging", "packaging"),
  ("platformdirs", "platformdirs"),
  ("click", "click"),
  ("typer", "typer"),
  ("python-multipart", "multipart"),
  ("httpx", "httpx"),
  ("aiohttp", "aiohttp"),
  ("websockets", "websockets"),
  ("pywebview", "webview"),
  ("psutil", "psutil"),
  ("GitPython", "git"),
]

REQUIRED_FILES = [
  "requirements.txt",
  "pyproject.toml",
  "src/phase2_uploads/app.py",
  "src/tools/cli.py",
  "AGENTS.md"
]

MAIN_IMPORT_PATH = "src.phase2_uploads.app:create_app"
MAIN_FILE_PATH = "src/phase2_uploads/app.py"


def _run(cmd: List[str]):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def check_system_info() -> Dict[str, str]:
    """Get system information."""
    return {
        'os': platform.system(),
        'version': platform.version(),
        'architecture': platform.machine(),
        'python_implementation': platform.python_implementation()
    }


def check_python() -> Dict[str, object]:
    """Check Python version with minimum requirement validation (>=3.11)."""
    try:
        ver_info = sys.version_info
        ver_str = f"Python {ver_info.major}.{ver_info.minor}.{ver_info.micro}"
        is_compatible = ver_info >= (3, 11)
        status = '✅' if is_compatible else '⚠️'
        return {
            'installed': True,
            'version': ver_str,
            'compatible': is_compatible,
            'status': status,
            'detail': '' if is_compatible else 'نسخه حداقل 3.11 نیاز است'
        }
    except Exception:
        return {'installed': False, 'version': None, 'compatible': False, 'status': '❌'}


def check_pip() -> Dict[str, object]:
    """Check if pip works via 'python -m pip'."""
    rc, out, err = _run([sys.executable, "-m", "pip", "--version"])
    if rc == 0:
        return {'installed': True, 'status': '✅', 'detail': out}
    return {'installed': False, 'status': '❌', 'detail': err}


def check_dependencies() -> Dict[str, Dict[str, str]]:
    """Check importability with version detail."""
    results: Dict[str, Dict[str, str]] = {}
    for pkg, module in REQUIRED_MODULES:
        try:
            mod = __import__(module)
            version = getattr(mod, '__version__', 'نامشخص')
            results[pkg] = {'status': '✅', 'version': version}
        except Exception as e:
            results[pkg] = {'status': '❌', 'version': '', 'error': str(e)[:80]}
    return results


def check_project_files() -> Dict[str, str]:
    results: Dict[str, str] = {}
    for rel in REQUIRED_FILES:
        p = PROJECT_ROOT / rel
        results[rel] = '✅' if p.exists() else '❌'
    return results


def _load_env_file() -> Dict[str, str]:
    """Load .env or .env.dev if present (very simple parser)."""
    env_path = PROJECT_ROOT / ".env"
    fallback = PROJECT_ROOT / ".env.dev"
    target = env_path if env_path.exists() else (fallback if fallback.exists() else None)
    data: Dict[str, str] = {}
    if not target:
        return data
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def check_config() -> Dict[str, object]:
    env = _load_env_file()
    status: Dict[str, object] = {}

    # .env
    env_exists = bool(env)
    status['env_file'] = '✅' if env_exists else '⚠️ (از .env.example کپی کنید)'

    # METRICS_TOKEN validation (min length 8) or IMPORT_TO_SABT_AUTH JSON-ish
    metrics_token = (env.get("METRICS_TOKEN", "") or "").strip()
    import_auth = (env.get("IMPORT_TO_SABT_AUTH", "") or "").strip()
    has_valid_token = (
        (len(metrics_token) >= 8) or 
        (len(import_auth) > 10 and '{' in import_auth)
    )
    status['metrics_token'] = '✅' if has_valid_token else '❌ (حداقل 8 کاراکتر)'

    # AGENTS.md present & non-trivial size
    agents_path = PROJECT_ROOT / "AGENTS.md"
    agents_exists = agents_path.exists()
    agents_size = agents_path.stat().st_size if agents_exists else 0
    status['agents_md'] = '✅' if (agents_exists and agents_size > 100) else '❌'

    # storage dirs (create if missing)
    storage_dir = PROJECT_ROOT / "tmp" / "uploads" / "storage"
    manifests_dir = PROJECT_ROOT / "tmp" / "uploads" / "manifests"
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        manifests_dir.mkdir(parents=True, exist_ok=True)
        status['storage_dirs'] = '✅'
    except Exception:
        status['storage_dirs'] = '❌ (خطا در ایجاد)'

    # Redis with timeout; fallback fakeredis if present
    try:
        import redis  # type: ignore
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=2)
        r.ping()
        status['redis'] = '✅ (localhost:6379 فعال)'
    except Exception:
        try:
            import fakeredis  # type: ignore
            status['redis'] = '⚠️ (fakeredis موجود - برای تست کافی است)'
        except Exception:
            status['redis'] = '❌ (نصب redis یا fakeredis توصیه می‌شود)'

    # Database: PostgreSQL optional, default SQLite
    db_url = (env.get("DATABASE_URL", "") or "")
    if "postgresql" in db_url.lower():
        try:
            import psycopg  # type: ignore
            status['database'] = '✅ (PostgreSQL پیکربندی شده)'
        except Exception:
            status['database'] = '⚠️ (psycopg نصب نیست)'
    else:
        status['database'] = '✅ (SQLite پیش‌فرض)'

    complete = (
        has_valid_token and 
        (status['agents_md'] == '✅') and 
        (status['storage_dirs'] == '✅')
    )
    status['complete'] = bool(complete)
    status['status'] = '✅' if complete else '⚠️'
    return status


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_disk_space() -> Dict[str, object]:
    """Check available disk space for project."""
    try:
        stat = shutil.disk_usage(PROJECT_ROOT)
        free_gb = stat.free / (1024**3)
        needed_gb = 2.0  # حداقل 2GB توصیه می‌شود
        return {
            'free_gb': round(free_gb, 2),
            'sufficient': free_gb >= needed_gb,
            'status': '✅' if free_gb >= needed_gb else '⚠️'
        }
    except Exception:
        return {'free_gb': 0, 'sufficient': False, 'status': '❌'}


def generate_report() -> bool:
    print("=" * 60)
    print(f"📊 وضعیت نصب و پیکربندی - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # سیستم‌عامل
    sys_info = check_system_info()
    print(f"\n💻 سیستم: {sys_info['os']} {sys_info['architecture']}")

    # Python
    py = check_python()
    print(f"\n1️⃣ پایتون: {py['status']}")
    if py['installed']:
        print(f"   نسخه: {py['version']}")
        if not py.get('compatible', True):
            print(f"   ⚠️ {py.get('detail', '')}")
    else:
        print("   ❌ نصب نشده - به مرحله ۱ بروید")

    # Pip
    pip = check_pip()
    print(f"\n2️⃣ مدیریت بسته‌ها (pip): {pip['status']}")
    if pip.get('detail'):
        print(f"   {pip['detail']}")

    # Dependencies
    deps = check_dependencies()
    all_deps_installed = all(info['status'] == '✅' for info in deps.values())
    missing = [pkg for pkg, info in deps.items() if info['status'] == '❌']
    print(f"\n3️⃣ کتابخانه‌های مورد نیاز: {'✅' if all_deps_installed else f'❌ ({len(missing)} مورد نصب نشده)'}")
    for pkg in missing:
        print(f"   ❌ {pkg}")
    installed_count = sum(1 for info in deps.values() if info['status'] == '✅')
    print(f"   ({installed_count}/{len(deps)} نصب شده)")

    # Project Files
    files = check_project_files()
    all_files_exist = all(v == '✅' for v in files.values())
    print(f\"\n4️⃣ فایل‌های پروژه: {'✅' if all_files_exist else '❌'}\")
    for file, status in files.items():
        if status == '❌':
            print(f\"   {status} {file}\")

    # Config
    cfg = check_config()
    print(f\"\n5️⃣ پیکربندی: {cfg.get('status')}\")
    print(f\"   .env: {cfg.get('env_file')}\")
    print(f\"   METRICS_TOKEN: {cfg.get('metrics_token')}\")
    print(f\"   AGENTS.md: {cfg.get('agents_md')}\")
    print(f\"   Redis: {cfg.get('redis')}\")
    print(f\"   Database: {cfg.get('database', 'N/A')}\")
    print(f\"   مسیرهای ذخیره: {cfg.get('storage_dirs')}\")

    # Disk
    disk = check_disk_space()
    print(f\"\n6️⃣ فضای دیسک: {disk['status']}\")
    print(f\"   فضای آزاد: {disk['free_gb']} GB\")

    # Progress
    print(\"\\n\" + \"=\" * 60)
    total_steps = 6
    completed_steps = sum([
        1 if py['installed'] and py.get('compatible', True) else 0,
        1 if pip['installed'] else 0,
        1 if all_deps_installed else 0,
        1 if all_files_exist else 0,
        1 if cfg.get('complete', False) else 0,
        1 if disk['sufficient'] else 0,
    ])
    progress = (completed_steps / total_steps) * 100

    # Visual progress bar
    bar_length = 30
    filled = int(bar_length * progress / 100)
    bar = '█' * filled + '░' * (bar_length - filled)

    print(f\"📈 پیشرفت کلی: {progress:.0f}% ({completed_steps}/{total_steps})\")
    print(f\"   [{bar}]\")
    print(\"=\" * 60)

    # Next step
    print(\"\\n🎯 مرحله بعدی شما:\")
    if not py['installed']:
        print(\"   ➡️ مرحله ۱: نصب پایتون 3.11+\")
        print(\"   لینک: https://www.python.org/downloads/\")
    elif not py.get('compatible', True):
        print(\"   ➡️ ارتقای پایتون به نسخه 3.11 یا بالاتر\")
    elif not pip['installed']:
        print(\"   ➡️ مرحله ۲: بررسی pip\")
        print(\"   دستور: python -m ensurepip --upgrade\")
    elif not all_deps_installed:
        print(f\"   ➡️ مرحله ۳: نصب {len(missing)} کتابخانه\")
        print(\"   دستور: اجرای فایل install_requirements.bat\")
    elif not all_files_exist:
        print(\"   ➡️ مرحله ۴: کپی فایل‌های پروژه\")
    elif not cfg.get('complete', False):
        print(\"   ➡️ مرحله ۵: تنظیمات پیکربندی\")
        if cfg.get('env_file') == '⚠️ (از .env.example کپی کنید)':
            print(\"   اقدام: کپی .env.example به .env\")
        if cfg.get('metrics_token') != '✅':
            print(\"   اقدام: تنظیم METRICS_TOKEN در فایل .env\")
        if cfg.get('agents_md') == '❌':
            print(\"   اقدام: بررسی وجود فایل AGENTS.md\")
    elif not disk['sufficient']:
        print(\"   ⚠️ فضای دیسک کم است (حداقل 2GB نیاز است)\")
    else:
        port_ok = _port_free(8000)
        print(\"   ✅ همه چیز آماده است! برنامه را اجرا کنید\")
        if port_ok:
            print(\"   دستور: اجرای فایل run_application.bat\")
            print(\"   آدرس: http://127.0.0.1:8000\")
        else:
            print(\"   ⚠️ پورت 8000 مشغول است\")
            print(\"   راه‌حل: در run_application.bat پورت را به 8080 تغییر دهید\")

    # Save log (optional)
    try:
        log_file = PROJECT_ROOT / \"installation_log.txt\"
        with open(log_file, \"a\", encoding=\"utf-8\") as f:
            f.write(f\"\\n{'='*60}\\n\")
            f.write(f\"Check time: {datetime.now()}\\n\")
            f.write(f\"Status: {'Complete' if completed_steps == total_steps else 'Incomplete'}\\n\")
            f.write(f\"Progress: {progress:.0f}%\\n\")
    except Exception:
        pass

    print(\"\\n\")
    return completed_steps == total_steps


if __name__ == \"__main__\":
    is_complete = generate_report()
    try:
        input(\"\\nبرای بستن این پنجره Enter بزنید...\")
    except Exception:
        pass
    sys.exit(0 if is_complete else 1)
