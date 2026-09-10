"""SSRF guard for server-side fetches of user-supplied URLs.

urllib-style openers speak `file://` (and friends), so every URL a user can
influence must pass through here before any fetch: only http(s), no embedded
credentials, and the host must resolve to a globally routable IP. Literal
IPs are checked without DNS; hostnames are resolved and *every* returned
address must be public (kills DNS-rebinding-by-round-robin for the common
single-lookup case).
"""
import ipaddress
import socket
from urllib.parse import urlparse

# Refuse pages larger than this (bomb protection + we only mine text).
MAX_FETCH_BYTES = 8 * 1024 * 1024
MAX_REDIRECT_HOPS = 3


class UnsafeUrlError(ValueError):
    """Raised when a user-supplied URL is not safe to fetch server-side."""


_LOCAL_NAMES = {"localhost", "localhost.", "local", "local.", "internal", "internal."}


def assert_public_http_url(url: str) -> str:
    """Validate `url` for server-side fetching. Returns the stripped URL.

    Raises UnsafeUrlError (a ValueError) on: non-string/empty input,
    non-http(s) scheme, embedded credentials, unresolvable hosts, and any
    host resolving to a non-public IP (loopback, private, link-local,
    multicast, reserved, unspecified).
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError("empty URL")
    cleaned = url.strip()
    parts = urlparse(cleaned)
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"only http(s) URLs may be fetched, got scheme {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials embedded in URL are not allowed")
    host = (parts.hostname or "").strip().rstrip(".")
    if not host:
        raise UnsafeUrlError("URL has no host")
    if host.lower() in _LOCAL_NAMES:
        raise UnsafeUrlError(f"host {host!r} is not public")
    if not resolve_public_ips(host):
        raise UnsafeUrlError(f"host {host!r} resolves to no public IP")
    return cleaned


def resolve_public_ips(host: str) -> list[str]:
    """Return the host's globally routable IPs, or [] if none / unresolvable.

    Literal IPs never touch DNS. Every resolved address must be public —
    one bad apple blocks the host (cheap DNS-rebinding round-robin cover).
    """
    host = (host or "").strip().rstrip(".")
    if not host or host.lower() in _LOCAL_NAMES:
        return []
    try:
        candidates = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return []
        candidates = []
        for info in infos:
            try:
                candidates.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    public = [str(c) for c in candidates if c.is_global and not c.is_multicast]
    if len(public) != len(candidates):
        return []
    return public
