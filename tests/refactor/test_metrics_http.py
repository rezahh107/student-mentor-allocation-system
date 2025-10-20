from __future__ import annotations

import http.client
import socket
import threading

from tools.refactor_imports import RefactorConfig
from tools.refactor_imports import _execute as execute_command


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_guarded_metrics_multiple_requests(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "AGENTS.md").write_text("spec", encoding="utf-8")
    src = project / "src"
    sma.mkdir()
    module = src / "main.py"
    module.write_text("from phase6_import_to_sabt import handler\n", encoding="utf-8")
    monkeypatch.chdir(project)

    port = _find_free_port()
    statuses: list[int] = []

    def _client() -> None:
        paths = ["/metrics?token=bad", "/metrics?token=token"]
        for path in paths:
            for _ in range(50):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    conn.request("GET", path)
                    resp = conn.getresponse()
                    statuses.append(resp.status)
                    resp.read()
                    break
                except (ConnectionRefusedError, ConnectionResetError):
                    continue
                finally:
                    conn.close()

    client_thread = threading.Thread(target=_client)
    client_thread.start()

    config = RefactorConfig(
        convert_relative=False,
        apply_changes=False,
        rate_limit=10,
        serve_metrics=True,
        metrics_port=port,
        metrics_token="token",
        metrics_requests=2,
    )
    execute_command("scan", config)
    client_thread.join()

    assert 403 in statuses
    assert 200 in statuses
