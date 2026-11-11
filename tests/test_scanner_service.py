"""The VM scanning service: token check, ClamAV protocol and fail-closed answers."""

import importlib.util
import json
import socket
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "operations" / "scanner" / "scanner_service.py"
TOKEN = "synthetic-scanner-token-7f3a9c2e5b1d8f4a6c0e"
EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


@pytest.fixture(autouse=True)
def records():
    # The service has no database; skip the application fixture.
    yield


def load_service():
    spec = importlib.util.spec_from_file_location("scanner_service", SERVICE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_clamd(path):
    """Answers PING and INSTREAM like clamd; flags payloads containing the EICAR marker."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(8)

    def handle(connection):
        with connection:
            command = b""
            while not command.endswith(b"\0"):
                command += connection.recv(1)
            if command == b"zPING\0":
                connection.sendall(b"PONG\0")
                return
            data = bytearray()
            while True:
                size = struct.unpack("!I", connection.recv(4, socket.MSG_WAITALL))[0]
                if size == 0:
                    break
                data.extend(connection.recv(size, socket.MSG_WAITALL))
            if EICAR_MARKER in data:
                connection.sendall(b"stream: Eicar-Signature FOUND\0")
            else:
                connection.sendall(b"stream: OK\0")

    def serve():
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(connection,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return server


@pytest.fixture
def scanner(tmp_path):
    module = load_service()
    socket_path = tmp_path / "clamd.ctl"
    clamd = fake_clamd(socket_path)
    config = {
        "token": TOKEN.encode(),
        "socket": str(socket_path),
        "max_bytes": 1024 * 1024,
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.make_handler(config))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", socket_path
    server.shutdown()
    clamd.close()


def call(url, data=None, token=TOKEN):
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_clean_and_infected_files_get_definite_answers(scanner):
    base, _ = scanner
    assert call(f"{base}/scan", b"%PDF-1.7 harmless") == (200, {"status": "clean"})
    infected = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + EICAR_MARKER + b"!$H+H*"
    assert call(f"{base}/scan", infected) == (200, {"status": "infected"})


def test_wrong_or_missing_token_is_refused(scanner):
    base, _ = scanner
    assert call(f"{base}/scan", b"data", token="wrong-token")[0] == 401
    assert call(f"{base}/scan", b"data", token=None)[0] == 401


def test_oversized_uploads_are_refused(scanner):
    base, _ = scanner
    assert call(f"{base}/scan", b"x" * (1024 * 1024 + 1))[0] == 413


def test_clamav_outage_fails_closed(scanner):
    base, socket_path = scanner
    assert call(f"{base}/health", token=None) == (200, {"status": "ready"})
    socket_path.unlink()  # ClamAV stopped: its socket is gone
    assert call(f"{base}/scan", b"data") == (503, {"status": "unavailable"})
    assert call(f"{base}/health", token=None) == (503, {"status": "unavailable"})


def test_service_refuses_to_start_without_a_strong_token(monkeypatch):
    module = load_service()
    monkeypatch.setenv("SCANNER_TOKEN", "short")
    with pytest.raises(SystemExit):
        module.settings()
