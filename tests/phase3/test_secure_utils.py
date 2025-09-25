from __future__ import annotations

import pytest

from scripts.secure_utils import parse_secure_xml, run_secure_command


def test_run_secure_command_allows_whitelisted() -> None:
    result = run_secure_command(["python", "-c", "print('salam')"])
    assert result.stdout.strip() == "salam"
    assert result.stderr == ""


def test_run_secure_command_rejects_unknown_command() -> None:
    with pytest.raises(ValueError):
        run_secure_command("ls -l")


def test_parse_secure_xml_success(tmp_path) -> None:
    xml_path = tmp_path / "sample.xml"
    xml_path.write_text("<root><value>1</value></root>", encoding="utf-8")
    tree = parse_secure_xml(xml_path)
    assert tree.getroot().tag == "root"


def test_parse_secure_xml_missing_file(tmp_path) -> None:
    missing_path = tmp_path / "missing.xml"
    with pytest.raises(FileNotFoundError):
        parse_secure_xml(missing_path)


def test_parse_secure_xml_large_file_rejected(tmp_path) -> None:
    big_path = tmp_path / "big.xml"
    big_path.write_bytes(b"<root>" + b"0" * (20 * 1024 * 1024 + 1) + b"</root>")
    with pytest.raises(ValueError):
        parse_secure_xml(big_path)

