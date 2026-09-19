"""SSRF guard unit tests (no network — resolution is monkeypatched)."""
import socket
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core.http import MAX_FETCH_BYTES, UnsafeUrlError, assert_public_http_url


@pytest.mark.parametrize("bad", [
    "",
    "   ",
    "file:///etc/passwd",
    "FILE:///etc/passwd",
    "ftp://example.com/x",
    "gopher://example.com/",
    "javascript:alert(1)",
    "data:text/plain,hi",
    "//example.com/no-scheme",
    "http://user:pass@example.com/",
    "http://[::1]/",
    "http://127.0.0.1/",
    "http://127.1.2.3/",
    "http://10.0.0.5/",
    "http://172.16.4.9/",
    "http://172.31.255.1/",
    "http://192.168.1.1/",
    "http://0.0.0.0/",
    "http://169.254.169.254/latest/meta-data/",
    "http://224.0.0.1/",
    "http://localhost/",
    "http://LOCALHOST:8000/admin",
    "http://[::ffff:127.0.0.1]/",
])
def test_blocked_urls(bad):
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url(bad)


def test_public_literal_ip_needs_no_dns():
    assert assert_public_http_url("http://93.184.216.34/ok") == "http://93.184.216.34/ok"


def test_public_hostname_with_mocked_dns(monkeypatch):
    def _fake_getaddrinfo(host, port, **kwargs):
        assert host == "example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    out = assert_public_http_url("https://example.com/some/page?q=1")
    assert out == "https://example.com/some/page?q=1"


def test_private_hostname_resolution_blocked(monkeypatch):
    def _fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.9.9", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("http://internal-app.example/")


def test_unresolvable_host_blocked(monkeypatch):
    def _boom(host, port, **kwargs):
        raise OSError("nope")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(UnsafeUrlError):
        assert_public_http_url("http://does-not-resolve.invalid/")


def test_max_fetch_bytes_sane():
    assert MAX_FETCH_BYTES == 8 * 1024 * 1024


def test_crawl_sync_rejects_blocked_start_url_without_network():
    from app.core.http import UnsafeUrlError
    from app.modules.rag.jobs import _crawl_sync

    with pytest.raises(UnsafeUrlError):
        _crawl_sync("http://169.254.169.254/latest/meta-data/", "single", 5)
    with pytest.raises(UnsafeUrlError):
        _crawl_sync("file:///etc/passwd", "single", 5)
