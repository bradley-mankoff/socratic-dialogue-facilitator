"""Injectable transport: protocol conformance and urllib behavior (SDF-3)."""

import pathlib
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dictionary.transport import (
    USER_AGENT,
    HttpResponse,
    Transport,
    TransportError,
    UrllibTransport,
)
from tests.stubs import StubTransport


def test_stub_transport_satisfies_protocol():
    assert isinstance(StubTransport({}), Transport)
    assert isinstance(UrllibTransport(), Transport)


class _Recorder(BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):
        type(self).captured["user_agent"] = self.headers.get("User-Agent")
        if self.path == "/ok":
            body = b"worked"
            self.send_response(200)
        else:
            body = b"boom"
            self.send_response(500)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep pytest output clean
        pass


def _serve():
    try:
        server = HTTPServer(("127.0.0.1", 0), _Recorder)
    except OSError:
        pytest.skip("no loopback sockets")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_urllib_transport_reports_200_and_500_on_loopback():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        transport = UrllibTransport(timeout=2.0)
        ok = transport.get(base + "/ok")
        assert isinstance(ok, HttpResponse)
        assert ok.status == 200
        assert ok.body == "worked"
        assert ok.url == base + "/ok"
        boom = transport.get(base + "/boom")
        assert boom.status == 500
        assert boom.body == "boom"
        assert _Recorder.captured["user_agent"] == USER_AGENT
    finally:
        server.shutdown()
        server.server_close()


def test_urllib_transport_wraps_connection_refused():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(TransportError):
        UrllibTransport(timeout=1.0).get(f"http://127.0.0.1:{port}/")


def test_urllib_transport_sends_user_agent():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        UrllibTransport(timeout=2.0).get(base + "/ok")
        assert _Recorder.captured["user_agent"] == USER_AGENT
    finally:
        server.shutdown()
        server.server_close()


def test_dictionary_sources_are_stdlib_only():
    root = pathlib.Path(__file__).resolve().parent.parent / "dictionary"
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(requests|httpx|aiohttp|urllib3)\b"
    )
    offenders = []
    for path in sorted(root.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if pattern.match(line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []
