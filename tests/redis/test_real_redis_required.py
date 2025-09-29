from __future__ import annotations

import contextlib
import socket
import threading
from dataclasses import dataclass
from typing import Iterator

import redis

from tests.hardened_api.redis_launcher import RedisLaunchSkipped, launch_redis_server


@dataclass(slots=True)
class MiniRedisState:
    store: dict[str, str]


class MiniRedisServer(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._stop_event = threading.Event()
        self._state = MiniRedisState(store={})

    def run(self) -> None:
        self._sock.listen()
        while not self._stop_event.is_set():
            try:
                client, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=0.1).close()
        except OSError:
            pass
        self._sock.close()
        self.join(timeout=1)

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            buffer = b""
            while not self._stop_event.is_set():
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data
                while True:
                    command, buffer = self._parse(buffer)
                    if command is None:
                        break
                    response = self._execute(command)
                    conn.sendall(response)

    def _parse(self, data: bytes) -> tuple[list[str] | None, bytes]:
        if not data:
            return None, data
        if data[:1] != b"*":
            return None, data
        end = data.find(b"\r\n")
        if end == -1:
            return None, data
        try:
            item_count = int(data[1:end])
        except ValueError:
            return None, data
        offset = end + 2
        items: list[str] = []
        for _ in range(item_count):
            if offset >= len(data) or data[offset:offset + 1] != b"$":
                return None, data
            end = data.find(b"\r\n", offset)
            if end == -1:
                return None, data
            length = int(data[offset + 1:end])
            start = end + 2
            stop = start + length
            if stop + 2 > len(data):
                return None, data
            items.append(data[start:stop].decode("utf-8"))
            offset = stop + 2
        return items, data[offset:]

    def _execute(self, command: list[str]) -> bytes:
        if not command:
            return b"-ERR empty command\r\n"
        op = command[0].upper()
        if op == "PING":
            return b"+PONG\r\n"
        if op == "SELECT" and len(command) >= 2:
            return b"+OK\r\n"
        if op == "FLUSHDB":
            self._state.store.clear()
            return b"+OK\r\n"
        if op == "SET" and len(command) >= 3:
            self._state.store[command[1]] = command[2]
            return b"+OK\r\n"
        if op == "GET" and len(command) >= 2:
            if command[1] in self._state.store:
                value = self._state.store[command[1]].encode("utf-8")
                return b"$" + str(len(value)).encode("utf-8") + b"\r\n" + value + b"\r\n"
            return b"$-1\r\n"
        return b"-ERR unsupported command\r\n"


@contextlib.contextmanager
def ensure_redis_runtime() -> Iterator[str]:
    try:
        with launch_redis_server() as runtime:
            yield runtime.url
            return
    except RedisLaunchSkipped:
        server = MiniRedisServer()
        server.start()
        try:
            yield f"redis://127.0.0.1:{server.port}/0"
        finally:
            server.stop()


def test_real_redis_fixture_active() -> None:
    with ensure_redis_runtime() as url:
        client = redis.Redis.from_url(url, decode_responses=True)
        client.flushdb()
        client.set("phase9:probe", "active")
        assert client.get("phase9:probe") == "active"
        client.flushdb()
