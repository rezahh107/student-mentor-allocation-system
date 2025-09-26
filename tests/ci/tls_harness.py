"""Local TLS Redis harness for integration testing of rediss:// flows."""
from __future__ import annotations

import socket
import ssl
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


class TLSRedisHarness:
    """Minimal RESP server wrapped in TLS for contract tests."""

    def __init__(
        self,
        cert_path: str,
        key_path: str,
        *,
        password: str = "ci-harness-secret",
        username: Optional[str] = None,
    ) -> None:
        self._cert_path = cert_path
        self._key_path = key_path
        self._password = password
        self._username = username
        self._bind_host = "127.0.0.1"
        self.hostname = "localhost"
        self.port: Optional[int] = None
        self._listener: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._state: Dict[int, Dict[str, str]] = defaultdict(dict)
        self._lock = threading.Lock()

    def __enter__(self) -> "TLSRedisHarness":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._bind_host, 0))
        listener.listen(5)
        self.port = listener.getsockname()[1]
        self._listener = listener
        self._stop.clear()

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=self._cert_path, keyfile=self._key_path)

        thread = threading.Thread(target=self._serve, args=(context,), daemon=True)
        thread.start()
        self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        if self._listener:
            try:
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._listener.close()
            self._listener = None
        for thread in list(self._threads):
            thread.join(timeout=1)
        self._threads.clear()

    def redis_url(self, *, db: int = 0, include_auth: bool = True) -> str:
        assert self.port is not None, "Harness must be started before requesting URL"
        auth_part = ""
        if include_auth and self._password:
            if self._username:
                auth_part = f"{self._username}:{self._password}@"
            else:
                auth_part = f":{self._password}@"
        return f"rediss://{auth_part}{self.hostname}:{self.port}/{db}"

    def dbsize(self, db: int = 0) -> int:
        with self._lock:
            return len(self._state.get(db, {}))

    def set_key(self, key: str, value: str, *, db: int = 0) -> None:
        with self._lock:
            self._state[db][key] = value

    def _serve(self, context: ssl.SSLContext) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._listener.accept()
            except OSError:
                break
            worker = threading.Thread(
                target=self._handle_client,
                args=(client, context),
                daemon=True,
            )
            worker.start()
            self._threads.append(worker)

    def _handle_client(self, conn: socket.socket, context: ssl.SSLContext) -> None:
        try:
            tls_conn = context.wrap_socket(conn, server_side=True)
        except ssl.SSLError:
            conn.close()
            return

        session = {"db": 0, "authed": self._password == "" or self._password is None}
        try:
            while not self._stop.is_set():
                command = self._read_command(tls_conn)
                if command is None:
                    break
                response, terminate = self._process_command(session, command)
                tls_conn.sendall(response)
                if terminate:
                    break
        finally:
            try:
                tls_conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            tls_conn.close()

    def _read_exact(self, sock: socket.socket, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("client disconnected")
            data.extend(chunk)
        return bytes(data)

    def _read_line(self, sock: socket.socket) -> Optional[bytes]:
        data = bytearray()
        while True:
            chunk = sock.recv(1)
            if not chunk:
                return None if not data else bytes(data)
            data.extend(chunk)
            if len(data) >= 2 and data[-2:] == b"\r\n":
                return bytes(data)

    def _read_command(self, sock: socket.socket) -> Optional[List[str]]:
        prefix = self._read_line(sock)
        if prefix is None:
            return None
        if not prefix.startswith(b"*"):
            return None
        try:
            count = int(prefix[1:-2])
        except ValueError:
            return None
        parts: List[str] = []
        for _ in range(count):
            header = self._read_line(sock)
            if not header or not header.startswith(b"$"):
                return None
            length = int(header[1:-2])
            payload = self._read_exact(sock, length)
            terminator = self._read_exact(sock, 2)
            if terminator != b"\r\n":
                return None
            parts.append(payload.decode("utf-8"))
        return parts

    def _process_command(self, session: Dict[str, object], parts: List[str]) -> Tuple[bytes, bool]:
        if not parts:
            return b"-ERR empty command\r\n", False
        command = parts[0].upper()

        if command == "AUTH":
            if len(parts) == 2:
                provided_user = None
                provided_pass = parts[1]
            elif len(parts) == 3:
                provided_user = parts[1]
                provided_pass = parts[2]
            else:
                return b"-ERR wrong number of arguments for 'auth' command\r\n", False

            if self._password and provided_pass != self._password:
                return b"-ERR invalid credentials\r\n", False
            if self._username and provided_user != self._username:
                return b"-ERR invalid credentials\r\n", False
            session["authed"] = True
            return b"+OK\r\n", False

        if not session.get("authed"):
            return b"-NOAUTH Authentication required\r\n", False

        if command == "SELECT":
            if len(parts) != 2:
                return b"-ERR wrong number of arguments for 'select' command\r\n", False
            try:
                db_index = int(parts[1])
            except ValueError:
                return b"-ERR invalid DB index\r\n", False
            if db_index < 0:
                return b"-ERR DB index must be non-negative\r\n", False
            session["db"] = db_index
            return b"+OK\r\n", False

        if command == "FLUSHDB":
            db_index = int(session.get("db", 0))
            with self._lock:
                self._state[db_index] = {}
            return b"+OK\r\n", False

        if command == "DBSIZE":
            db_index = int(session.get("db", 0))
            with self._lock:
                size = len(self._state.get(db_index, {}))
            return f":{size}\r\n".encode("utf-8"), False

        if command == "SET":
            if len(parts) < 3:
                return b"-ERR wrong number of arguments for 'set' command\r\n", False
            db_index = int(session.get("db", 0))
            with self._lock:
                self._state.setdefault(db_index, {})[parts[1]] = parts[2]
            return b"+OK\r\n", False

        if command == "GET":
            if len(parts) != 2:
                return b"-ERR wrong number of arguments for 'get' command\r\n", False
            db_index = int(session.get("db", 0))
            with self._lock:
                value = self._state.get(db_index, {}).get(parts[1])
            if value is None:
                return b"$-1\r\n", False
            encoded = value.encode("utf-8")
            return f"${len(encoded)}\r\n".encode("utf-8") + encoded + b"\r\n", False

        if command == "PING":
            return b"+PONG\r\n", False

        if command == "QUIT":
            return b"+OK\r\n", True

        return b"-ERR unsupported command\r\n", False


__all__ = ["TLSRedisHarness"]
