from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

import pytest
from prometheus_client import CollectorRegistry

from windows_service.errors import ServiceError
from windows_service import winsw_xml
from windows_service.winsw_xml import write_winsw_xml


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in winsw_xml.REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in winsw_xml.REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def registry() -> CollectorRegistry:
    return CollectorRegistry()


def _prepare_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "Start-App.ps1").write_text("Write-Host 'noop'", encoding="utf-8")
    (repo_root / "windows_service").mkdir()
    return repo_root


def _write_env(path: Path, *, token: str) -> Path:
    payload = (
        "DATABASE_URL=postgresql://postgres‌:postgres@localhost:5432/postgres\n"
        "REDIS_URL=redis://localhost:6379/۰\n"
        f"METRICS_TOKEN=\"{token}\"\n"
    )
    target = path / ".env.dev"
    target.write_text(payload, encoding="utf-8")
    return target


def _parse_xml(path: Path) -> ET.Element:
    tree = ET.parse(path)
    return tree.getroot()


def test_atomic_write_and_no_partials(tmp_path: Path, registry: CollectorRegistry):
    repo_root = _prepare_repo(tmp_path)
    env_file = _write_env(repo_root, token="metrics-token-۱")
    output_path = repo_root / "windows_service" / "StudentMentorService.xml"

    result_path = write_winsw_xml(
        env_path=env_file,
        output_path=output_path,
        repo_root=repo_root,
        pwsh_path="C:/Program Files/PowerShell/7/pwsh.exe",
        registry=registry,
    )

    assert result_path == output_path
    assert output_path.exists()
    assert not list(output_path.parent.glob("StudentMentorService.xml*.part")), {
        "xml_path": str(output_path)
    }

    success_value = registry.get_sample_value(
        "winsw_xml_write_total", {"outcome": "success"}
    )
    assert success_value == pytest.approx(1)

    root = _parse_xml(output_path)
    assert root.findtext("executable") == str(PureWindowsPath("C:/Program Files/PowerShell/7/pwsh.exe"))
    expected_script = str(PureWindowsPath(repo_root / "Start-App.ps1"))
    assert root.findtext("arguments") == (
        f"-NoLogo -NoProfile -ExecutionPolicy Bypass -File {expected_script}"
    )
    assert root.findtext("workingdirectory") == str(PureWindowsPath(repo_root))

    log = root.find("log")
    assert log is not None and log.get("mode") == "roll-by-size"
    assert log.findtext("sizeThreshold") == "10485760"
    assert log.findtext("keepFiles") == "8"

    env_nodes = {node.get("name"): node.get("value") for node in root.findall("env")}
    assert env_nodes["PYTHONUTF8"] == "1"
    assert env_nodes["PYTHONPATH"] == str(PureWindowsPath(repo_root / "src"))
    assert env_nodes["DATABASE_URL"].startswith("postgresql://postgres:postgres")
    assert env_nodes["REDIS_URL"].endswith("/0"), env_nodes["REDIS_URL"]
    assert env_nodes["METRICS_TOKEN"] == "metrics-token-1"


def test_pretty_formatting_produces_multiline(tmp_path: Path, registry: CollectorRegistry):
    repo_root = _prepare_repo(tmp_path)
    env_file = _write_env(repo_root, token="metrics-token-۱")
    output_path = repo_root / "windows_service" / "StudentMentorService.xml"

    write_winsw_xml(
        env_path=env_file,
        output_path=output_path,
        repo_root=repo_root,
        pwsh_path="C:/Program Files/PowerShell/7/pwsh.exe",
        pretty=True,
        registry=registry,
    )

    xml_text = output_path.read_text(encoding="utf-8")
    assert "<?xml version=\"1.0\" encoding=\"utf-8\"?>" in xml_text.splitlines()[0]
    assert "\n" in xml_text
    assert "<env name=\"DATABASE_URL\"" in xml_text


def test_missing_pwsh_raises_persian_error(
    tmp_path: Path, registry: CollectorRegistry, monkeypatch: pytest.MonkeyPatch
):
    repo_root = _prepare_repo(tmp_path)
    env_file = _write_env(repo_root, token="metrics-token-۱")
    monkeypatch.delenv("SMASM_PWSH", raising=False)
    monkeypatch.setattr("windows_service.winsw_xml.shutil.which", lambda _: None)
    with pytest.raises(ServiceError) as captured:
        write_winsw_xml(
            env_path=env_file,
            repo_root=repo_root,
            pwsh_path=None,
            registry=registry,
        )
    assert captured.value.code == "POWERSHELL_MISSING"
    assert "PowerShell" in captured.value.message


def test_concurrent_writes_leave_single_file(tmp_path: Path, registry: CollectorRegistry):
    repo_root = _prepare_repo(tmp_path)
    xml_path = repo_root / "windows_service" / "StudentMentorService.xml"

    def _worker(idx: int) -> None:
        env_file = repo_root / f".env.dev.{idx}"
        token = f"metrics-{idx}"
        env_file.write_text(
            f"DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres\n"
            f"REDIS_URL=redis://localhost:6379/{idx}\n"
            f"METRICS_TOKEN={token}\n",
            encoding="utf-8",
        )
        write_winsw_xml(
            env_path=env_file,
            output_path=xml_path,
            repo_root=repo_root,
            pwsh_path="C:/Program Files/PowerShell/7/pwsh.exe",
            registry=registry,
        )

    threads = [threading.Thread(target=_worker, args=(idx,)) for idx in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert xml_path.exists()
    assert not list(xml_path.parent.glob("StudentMentorService.xml*.part")), {
        "xml_path": str(xml_path)
    }
    parsed = _parse_xml(xml_path)
    env_tokens = {
        node.get("value")
        for node in parsed.findall("env")
        if node.get("name") == "METRICS_TOKEN"
    }
    assert env_tokens, {"xml": xml_path.read_text(encoding="utf-8")}
    final_token = env_tokens.pop()
    assert final_token in {"metrics-0", "metrics-1", "metrics-2"}
