# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from types import SimpleNamespace


from src.phase2_counter_service import cli
from src.phase2_counter_service.backfill import BackfillStats


def _non_empty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def test_cli_assign_counter(monkeypatch, capsys):
    captured = {}

    def fake_assign(national_id: str, gender: int, year_code: str) -> str:
        captured["args"] = (national_id, gender, year_code)
        return "253731234"

    monkeypatch.setattr(cli, "assign_counter", fake_assign)
    exit_code = cli.main(["assign-counter", "1234567890", "0", "25"])
    out = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert out == "253731234"
    assert captured["args"] == ("1234567890", 0, "25")


def test_stdout_observer_emits_json(capsys):
    observer = cli.StdoutObserver()
    observer.on_chunk(3, 7, 2, 1)
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"chunk": 3, "applied": 7, "reused": 2, "skipped": 1}


def test_cli_backfill(monkeypatch, capsys, tmp_path):
    stats = BackfillStats(
        total_rows=10,
        applied=4,
        reused=6,
        skipped=0,
        dry_run=False,
        prefix_mismatches=1,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    exit_code = cli.main(["backfill", str(tmp_path / "file.csv"), "--chunk-size", "5", "--apply"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] == 4
    assert payload["dry_run"] is False
    assert payload["prefix_mismatches"] == 1


def test_cli_backfill_writes_excel_safe_csv(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=5,
        applied=2,
        reused=1,
        skipped=2,
        dry_run=True,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    csv_path = tmp_path / "result.csv"
    args = [
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(csv_path),
        "--excel-safe",
        "--bom",
        "--crlf",
        "--quote-all",
    ]
    exit_code = cli.main(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    lines = _non_empty_lines(captured.out)
    assert lines[0] == f"گزارش آمار در «{csv_path}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is True
    assert payload["stats_csv_path"] == str(csv_path)
    content_bytes = csv_path.read_bytes()
    assert content_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in content_bytes
    content = content_bytes.decode("utf-8")
    lines = [line for line in content.splitlines() if line]
    assert '"total_rows","5"' in lines
    assert '"dry_run","بله"' in lines
    assert all(not line.startswith('"\'') for line in lines[1:])


def test_cli_stats_csv_localization_and_digits(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=12,
        applied=7,
        reused=4,
        skipped=1,
        dry_run=False,
        prefix_mismatches=3,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    csv_path = tmp_path / "localized.csv"
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    exit_code = cli.main([
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(csv_path),
    ])
    assert exit_code == 0
    output = capsys.readouterr()
    lines = _non_empty_lines(output.out)
    assert lines[0] == f"گزارش آمار در «{csv_path}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is False
    assert payload["stats_csv_path"] == str(csv_path)
    payload = csv_path.read_text(encoding="utf-8")
    assert "خیر" in payload
    assert "۷" not in payload


def test_cli_stats_csv_overwrite_guard(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=1,
        applied=1,
        reused=0,
        skipped=0,
        dry_run=True,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    target = tmp_path / "existing.csv"
    target.write_text("legacy", encoding="utf-8")
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    args = [
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(target),
    ]
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "بازنویسی" in captured.err
    assert json.loads(captured.out)["applied"] == 1
    assert target.read_text(encoding="utf-8") == "legacy"

    capsys.readouterr()
    exit_code = cli.main(args + ["--overwrite"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "بله" in target.read_text(encoding="utf-8")
    lines = _non_empty_lines(captured.out)
    assert lines[0] == f"گزارش آمار در «{target}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is True
    assert payload["stats_csv_path"] == str(target)


def test_cli_stats_csv_directory_suffix(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=8,
        applied=4,
        reused=4,
        skipped=0,
        dry_run=True,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    target_dir = tmp_path / "stats"
    target_dir.mkdir()
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    monkeypatch.setattr(cli, "_timestamp_suffix", lambda: "20230101T120000")

    class _UUID:
        hex = "cafebabedeadbeef"

    monkeypatch.setattr(cli.uuid, "uuid4", lambda: _UUID())

    exit_code = cli.main([
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(target_dir),
        "--excel-safe",
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    created = list(target_dir.glob("*.csv"))
    assert len(created) == 1
    expected_name = "backfill_stats_20230101T120000_cafeba.csv"
    assert created[0].name == expected_name
    payload = created[0].read_text(encoding="utf-8")
    assert "بله" in payload
    lines = _non_empty_lines(captured.out)
    expected_path = target_dir / expected_name
    assert lines[0] == f"گزارش آمار در «{expected_path}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is True
    assert payload["stats_csv_path"] == str(expected_path)


def test_cli_stats_csv_creates_missing_directory(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=9,
        applied=3,
        reused=6,
        skipped=0,
        dry_run=True,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    target_dir = tmp_path / "reports"
    assert not target_dir.exists()
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    monkeypatch.setattr(cli, "_timestamp_suffix", lambda: "20240229T010203")

    class _UUID:
        hex = "feedfacecafefeed"

    monkeypatch.setattr(cli.uuid, "uuid4", lambda: _UUID())

    exit_code = cli.main([
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(target_dir) + os.sep,
        "--excel-safe",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    expected_path = target_dir / "backfill_stats_20240229T010203_feedfa.csv"
    assert expected_path.exists()
    assert target_dir.is_dir()
    lines = _non_empty_lines(captured.out)
    assert lines[0] == f"گزارش آمار در «{expected_path}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is True
    assert payload["stats_csv_path"] == str(expected_path)


def test_cli_stats_csv_path_without_suffix_treated_as_directory(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=5,
        applied=5,
        reused=0,
        skipped=0,
        dry_run=False,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        return stats

    root_dir = tmp_path / "reports"
    target = root_dir / "monthly"
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    monkeypatch.setattr(cli, "_timestamp_suffix", lambda: "20240301T101112")

    class _UUID:
        hex = "0011223344556677"

    monkeypatch.setattr(cli.uuid, "uuid4", lambda: _UUID())

    exit_code = cli.main([
        "backfill",
        str(tmp_path / "input.csv"),
        "--stats-csv",
        str(target),
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    expected_dir = target
    expected_path = expected_dir / "backfill_stats_20240301T101112_001122.csv"
    assert expected_dir.is_dir()
    assert expected_path.exists()
    lines = _non_empty_lines(captured.out)
    assert lines[0] == f"گزارش آمار در «{expected_path}» ذخیره شد."
    payload = json.loads(lines[-1])
    assert payload["dry_run"] is False
    assert payload["stats_csv_path"] == str(expected_path)


def test_cli_backfill_json_only_suppresses_banner(monkeypatch, tmp_path, capsys):
    stats = BackfillStats(
        total_rows=3,
        applied=3,
        reused=0,
        skipped=0,
        dry_run=False,
        prefix_mismatches=0,
    )

    def fake_run(service, path, **kwargs):  # noqa: ARG001
        assert kwargs["observer"] is None
        return stats

    csv_path = tmp_path / "only.json.csv"
    monkeypatch.setattr(cli, "get_service", lambda: None)
    monkeypatch.setattr(cli, "run_backfill", fake_run)
    exit_code = cli.main(
        [
            "backfill",
            str(tmp_path / "input.csv"),
            "--stats-csv",
            str(csv_path),
            "--json-only",
            "--verbose",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    output = captured.out.strip()
    payload = json.loads(output)
    assert payload["stats_csv_path"] == str(csv_path)
    assert csv_path.exists()
    assert "گزارش آمار" not in captured.out
    assert captured.err == ""


def test_cli_metrics(monkeypatch):
    events = []

    class FakeServer:
        def __init__(self) -> None:
            events.append("init")

        def start(self, port: int) -> None:
            events.append(("start", port))

        def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(cli, "MetricsServer", FakeServer)
    monkeypatch.setattr(cli, "get_config", lambda: SimpleNamespace(metrics_port=9109))
    exit_code = cli.main(["serve-metrics", "--oneshot", "--port", "9107"])
    assert exit_code == 0
    assert events == ["init", ("start", 9107), "stop"]


def test_cli_metrics_duration(monkeypatch):
    events = []

    class FakeServer:
        def start(self, port: int) -> None:
            events.append(("start", port))

        def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(cli, "MetricsServer", FakeServer)
    monkeypatch.setattr(cli, "get_config", lambda: SimpleNamespace(metrics_port=9200))
    exit_code = cli.main(["serve-metrics", "--duration", "0.01"])
    assert exit_code == 0
    assert events[0] == ("start", 9200)
    assert events[-1] == "stop"


def test_cli_metrics_indefinite_loop(monkeypatch):
    events = []

    class FakeServer:
        def start(self, port: int) -> None:
            events.append(("start", port))

        def stop(self) -> None:
            events.append("stop")

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "MetricsServer", FakeServer)
    monkeypatch.setattr(cli, "get_config", lambda: SimpleNamespace(metrics_port=9300))
    monkeypatch.setattr(cli.time, "sleep", fake_sleep)

    exit_code = cli.main(["serve-metrics"])

    assert exit_code == 0
    assert events == [("start", 9300), "stop"]
    assert sleeps == [1]


def test_cli_assign_counter_error(monkeypatch, capsys):
    def fake_assign(*args):
        raise ValueError('boom')

    monkeypatch.setattr(cli, 'assign_counter', fake_assign)
    exit_code = cli.main(['assign-counter', '1234567890', '0', '25'])
    out = capsys.readouterr()
    assert exit_code == 1
    assert 'boom' in out.err
