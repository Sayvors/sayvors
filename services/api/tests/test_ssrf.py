"""P1 SSRF guard proofs: DB-source hosts must be publicly routable.

Literal IPs never touch DNS; hostnames must resolve exclusively to global
IPs. These tests prove the guard blocks loopback/private/link-local/
metadata targets and honors the private-host escape hatch — without opening
any socket (except the rebinding simulation, which stubs getaddrinfo).
"""
import pytest

from app.modules.rag.connectors import DbConfig, _assert_connectable_host


def _cfg(host: str) -> DbConfig:
    return DbConfig(db_type="postgres", host=host, port=5432,
                    database="d", username="u", password="p")


@pytest.mark.parametrize("host", [
    "127.0.0.1",          # loopback
    "::1",                # v6 loopback
    "10.0.0.5",           # RFC1918
    "172.16.0.1",         # RFC1918
    "192.168.1.1",        # RFC1918
    "169.254.169.254",    # cloud metadata endpoint
    "0.0.0.0",            # unspecified
    "100.64.0.1",         # CGNAT shared space
    "localhost",          # local name
    "LOCALHOST.",         # trailing dot + case
    "2130706433",         # decimal-encoded 127.0.0.1
    "",                   # empty
    "   ",                # blank
])
def test_private_hosts_rejected(host):
    with pytest.raises(ValueError, match="publicly reachable|required"):
        _assert_connectable_host(_cfg(host))


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "9.9.9.9"])
def test_public_literals_allowed(host):
    # Pure check — must not raise and must not open any socket.
    _assert_connectable_host(_cfg(host))


def test_dns_rebinding_mixed_blocked(monkeypatch):
    """One private address among the answers blocks the whole host."""
    import socket

    def _fake_getaddrinfo(host, port, type=None, *a, **k):
        assert host == "rebind.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.0", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.9.9", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(ValueError, match="publicly reachable"):
        _assert_connectable_host(_cfg("rebind.example"))


def test_dns_all_public_allowed(monkeypatch):
    import socket

    def _fake_getaddrinfo(host, port, type=None, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.0", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    _assert_connectable_host(_cfg("public.example"))


def test_private_allowlist_escape_hatch(monkeypatch):
    """Self-hosted deployments can opt into private targets explicitly."""
    from app.config import settings

    monkeypatch.setattr(settings, "RAG_DB_ALLOW_PRIVATE_HOSTS", True)
    _assert_connectable_host(_cfg("192.168.1.50"))  # no raise


@pytest.mark.asyncio
async def test_connection_never_dials_blocked_host(monkeypatch):
    """test_connection must fail at the guard, before any driver runs."""
    from app.modules.rag import connectors

    async def _boom(cfg, sql, args=()):
        raise AssertionError("driver must not run for blocked hosts")

    monkeypatch.setattr(connectors, "_fetch", _boom)
    with pytest.raises(ValueError, match="publicly reachable"):
        await connectors.test_connection(_cfg("169.254.169.254"))
