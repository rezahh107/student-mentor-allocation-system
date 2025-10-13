from __future__ import annotations

from types import SimpleNamespace

from windows_service.controller import EXIT_SUCCESS, ServiceController


def test_console_run_lifecycle(tmp_path, monkeypatch):
    exe_path = tmp_path / "StudentMentorService.exe"
    xml_path = tmp_path / "StudentMentorService.xml"
    exe_path.write_text("stub", encoding="utf-8")
    xml_path.write_text("<service/>", encoding="utf-8")

    executed: list[tuple[str, str]] = []

    def executor(args: list[str]):
        executed.append(tuple(args))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    runner_calls: list[int] = []

    def runner(port: int) -> None:
        runner_calls.append(port)

    controller = ServiceController(
        winsw_executable=exe_path,
        winsw_xml=xml_path,
        executor=executor,
        uvicorn_runner=runner,
    )

    assert controller.handle("install") == EXIT_SUCCESS
    assert controller.handle("start") == EXIT_SUCCESS
    assert executed == [
        (str(exe_path), "install"),
        (str(exe_path), "start"),
    ]

    monkeypatch.setenv("DATABASE_URL", "postgres://localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/1")
    monkeypatch.setenv("METRICS_TOKEN", "metrics-token")

    assert controller.handle("run") == EXIT_SUCCESS
    assert runner_calls  # run invoked with resolved port
    assert 1024 <= runner_calls[0] <= 49151
