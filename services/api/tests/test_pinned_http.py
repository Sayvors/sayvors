"""DNS-pinning transport tests.

No external network: dial-target is asserted with a spy backend, and the
end-to-end test serves loopback HTTP with validation allowlisted for
127.0.0.1 only.
"""
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpcore

from app.core import pinned_http
from app.core.http import UnsafeUrlError


def test_backend_dials_pinned_ip_not_url_host(monkeypatch):
    seen = {}

    def _fake_connect(self, host, port=None, timeout=None, local_address=None, socket_options=None):
        seen.update(host=host, port=port)
        raise RuntimeError("stop here — dial target captured")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _fake_connect)
    backend = pinned_http._PinnedBackend("93.184.216.34")
    with pytest.raises(RuntimeError, match="stop here"):
        backend.connect_tcp("evil-attacker.test", 443, timeout=5)
    assert seen == {"host": "93.184.216.34", "port": 443}


class _Handler(BaseHTTPRequestHandler):
    server_version = "TestLoopback/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"hello pinned world"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "99999999")
            self.end_headers()
            self.wfile.write(b"tiny")
        elif self.path == "/bin":
            body = b"\x00\x01\x02"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/evil-redir":
            self.send_response(302)
            self.send_header("Location", "http://10.9.9.9/")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def loopback():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def loopback_allowed(monkeypatch):
    """Allowlist loopback for validation + resolution (test-only)."""
    monkeypatch.setattr(
        pinned_http, "assert_public_http_url", lambda url: url.strip()
    )
    monkeypatch.setattr(pinned_http, "resolve_public_ips", lambda host: ["127.0.0.1"])
    return True


def test_loopback_e2e_with_redirect(loopback, loopback_allowed):
    assert pinned_http.fetch_pinned(f"{loopback}/ok") == "hello pinned world"
    assert pinned_http.fetch_pinned(f"{loopback}/redir") == "hello pinned world"


def test_loopback_size_and_type_caps(loopback, loopback_allowed):
    with pytest.raises(ValueError, match="size limit"):
        pinned_http.fetch_pinned(f"{loopback}/big")
    with pytest.raises(ValueError, match="not a crawlable page"):
        pinned_http.fetch_pinned(f"{loopback}/bin")


def test_redirect_to_private_ip_blocked_before_connect(loopback, loopback_allowed, monkeypatch):
    dialed = []

    orig_resolve = pinned_http.resolve_public_ips

    def _resolve(host):
        if host == "10.9.9.9":
            return []  # re-resolution at the hop finds nothing public
        return orig_resolve(host)

    monkeypatch.setattr(pinned_http, "resolve_public_ips", _resolve)

    orig_connect = httpcore.SyncBackend.connect_tcp

    def _spy(self, host, port=None, timeout=None, local_address=None, socket_options=None):
        dialed.append(host)
        return orig_connect(self, host, port, timeout, local_address, socket_options)

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy)
    with pytest.raises(UnsafeUrlError):
        pinned_http.fetch_pinned(f"{loopback}/evil-redir")
    assert dialed, "expected the initial loopback dial"
    assert "10.9.9.9" not in dialed, "must never dial the rebinding target"


def test_guard_still_blocks_without_allowlist():
    with pytest.raises(UnsafeUrlError):
        pinned_http.fetch_pinned("http://127.0.0.1:9/")
