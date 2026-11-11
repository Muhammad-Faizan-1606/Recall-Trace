"""RecallTrace malware scanning service.

Runs on the scanner VM behind Caddy (which provides HTTPS) and hands each upload to the
local ClamAV daemon over its Unix socket. Standard library only.

    POST /scan    Authorization: Bearer <SCANNER_TOKEN>, body = file bytes
                  200 {"status": "clean"} or {"status": "infected"}
                  401 wrong or missing token, 413 too large, 503 ClamAV unavailable
    GET  /health  200 {"status": "ready"} when ClamAV answers PING, otherwise 503

File contents and the token are never logged. Anything other than a definite ClamAV
answer is reported as unavailable, so RecallTrace keeps the file quarantined.
"""

import hmac
import json
import os
import socket
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK = 64 * 1024


def settings():
    token = os.environ.get("SCANNER_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set SCANNER_TOKEN to a random value of at least 32 characters.")
    return {
        "token": token.encode(),
        "socket": os.environ.get("CLAMD_SOCKET", "/var/run/clamav/clamd.ctl"),
        "max_bytes": int(os.environ.get("SCANNER_MAX_BYTES", str(12 * 1024 * 1024))),
        "host": os.environ.get("SCANNER_HOST", "127.0.0.1"),
        "port": int(os.environ.get("SCANNER_PORT", "8088")),
    }


def _clamd(socket_path, timeout=60):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(socket_path)
    return connection


def _reply(connection, limit=4096):
    data = bytearray()
    while len(data) < limit:
        chunk = connection.recv(limit - len(data))
        if not chunk:
            break
        data.extend(chunk)
        if b"\0" in chunk:
            break
    return bytes(data).split(b"\0", 1)[0].strip()


def ping(socket_path):
    with _clamd(socket_path, timeout=5) as connection:
        connection.sendall(b"zPING\0")
        return _reply(connection) == b"PONG"


def scan(data, socket_path):
    """Return 'clean' or 'infected'; raise OSError/ValueError for anything else."""
    with _clamd(socket_path) as connection:
        connection.sendall(b"zINSTREAM\0")
        for start in range(0, len(data), CHUNK):
            block = data[start : start + CHUNK]
            connection.sendall(struct.pack("!I", len(block)) + block)
        connection.sendall(struct.pack("!I", 0))
        reply = _reply(connection)
    if reply.endswith(b": OK"):
        return "clean"
    if reply.endswith(b" FOUND"):
        return "infected"
    raise ValueError("ClamAV did not return a definite result.")


def make_handler(config):
    class ScannerHandler(BaseHTTPRequestHandler):
        server_version = "RecallTraceScanner"
        sys_version = ""

        def _send(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            # Method, path and status only; never headers, tokens or file contents.
            print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}")

        def do_GET(self):
            if self.path != "/health":
                return self._send(404, {"status": "not_found"})
            try:
                ready = ping(config["socket"])
            except OSError:
                ready = False
            return self._send(
                200 if ready else 503, {"status": "ready" if ready else "unavailable"}
            )

        def do_POST(self):
            if self.path != "/scan":
                return self._send(404, {"status": "not_found"})
            supplied = self.headers.get("Authorization", "")
            expected = b"Bearer " + config["token"]
            if not hmac.compare_digest(supplied.encode(), expected):
                return self._send(401, {"status": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._send(411, {"status": "length_required"})
            if length < 0 or length > config["max_bytes"]:
                return self._send(413, {"status": "too_large"})
            data = self.rfile.read(length)
            if len(data) != length:
                return self._send(400, {"status": "incomplete"})
            try:
                return self._send(200, {"status": scan(data, config["socket"])})
            except (OSError, ValueError):
                return self._send(503, {"status": "unavailable"})

        def do_PUT(self):
            self._send(405, {"status": "method_not_allowed"})

        do_DELETE = do_PATCH = do_PUT

    return ScannerHandler


def main():
    config = settings()
    server = ThreadingHTTPServer((config["host"], config["port"]), make_handler(config))
    print(f"RecallTrace scanner listening on {config['host']}:{config['port']}")
    server.serve_forever()


if __name__ == "__main__":
    main()
