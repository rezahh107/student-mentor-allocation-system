# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from types import SimpleNamespace


from src.phase2_counter_service import cli
from src.phase2_counter_service.backfill import BackfillStats


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
