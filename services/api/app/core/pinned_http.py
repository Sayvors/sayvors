"""DNS-rebinding-proof fetching for user-supplied URLs.

Threat: validation resolves example.com -> public 1.2.3.4, but the fetch
re-resolves and the attacker's DNS now answers 127.0.0.1 (TOCTOU). Fix:
resolve ONCE via resolve_public_ips(), then dial exactly that IP while
keeping the original hostname for the Host header, TLS SNI and cert
verification (all derived from the request URL by httpcore, untouched).

Each redirect hop is re-validated AND re-pinned, so cross-host redirects
can't smuggle a private target through a public start URL either.
"""
from urllib.parse import urljoin, urlparse

import httpcore

from .http import (
    MAX_FETCH_BYTES,
    MAX_REDIRECT_HOPS,
    UnsafeUrlError,
    assert_public_http_url,
    resolve_public_ips,
)

_REDIRECTS = {301, 302, 303, 307, 308}
_CRAWLABLE_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_TIMEOUTS = {"connect": 10.0, "read": 20.0, "write": 10.0, "pool": 10.0}


class _PinnedBackend(httpcore.SyncBackend):
    """Network backend that TCP-dials a pre-validated IP.

    Only the dial target changes: Host header, SNI and certificate checks
    keep using the request's original hostname (httpcore derives those from
    the URL/origin, never from the socket peer).
    """

    def __init__(self, ip: str):
        self._ip = ip

    def connect_tcp(self, host: str, port: int, timeout=None, local_address=None, socket_options=None):
        return super().connect_tcp(
            self._ip, port, timeout, local_address, socket_options
        )


def _read_text(resp: httpcore.Response) -> str:
    ctype = ""
    length = None
    for name, value in resp.headers:
        key = name.decode("latin-1").lower()
        if key == "content-type":
            ctype = value.decode("latin-1").split(";")[0].strip().lower()
        elif key == "content-length" and value.decode("latin-1").strip().isdigit():
            length = int(value.decode("latin-1").strip())
    if ctype and ctype not in _CRAWLABLE_TYPES:
        raise ValueError(f"not a crawlable page (content-type: {ctype or 'unknown'})")
    if length is not None and length > MAX_FETCH_BYTES:
        raise ValueError("page exceeds size limit")
    # Stream with our own cap: Content-Length may lie or be absent.
    body = bytearray()
    for chunk in resp.stream:
        body += chunk
        if len(body) > MAX_FETCH_BYTES:
            raise ValueError("page exceeds size limit")
    return bytes(body).decode("utf-8", errors="ignore")


def fetch_pinned(url: str, *, timeout: float = 20.0, user_agent: str = "SayvorsBot/1.0") -> str:
    """GET a user-supplied URL with SSRF validation + DNS pinning.

    Returns decoded text. Raises UnsafeUrlError (ValueError) for blocked
    URLs, ValueError for oversize/non-HTML/too-many-redirects, and
    httpcore exceptions for transport failures.
    """
    timeouts = {"connect": min(10.0, timeout), "read": timeout, "write": 10.0, "pool": 10.0}
    current = assert_public_http_url(url)
    for _ in range(MAX_REDIRECT_HOPS + 1):
        parts = urlparse(current)
        host = (parts.hostname or "").rstrip(".")
        ips = resolve_public_ips(host)
        if not ips:
            # Re-check every hop: DNS may have flipped since validation.
            raise UnsafeUrlError(f"host {host!r} resolves to no public IP")
        host_header = host
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            port = 443 if parts.scheme == "https" else 80
        if (parts.scheme == "https" and port != 443) or (parts.scheme == "http" and port != 80):
            host_header = f"{host}:{port}"
        pool = httpcore.ConnectionPool(
            network_backend=_PinnedBackend(ips[0]),
        )
        try:
            req = httpcore.Request(
                "GET",
                current,
                headers=[
                    (b"user-agent", user_agent.encode("utf-8")),
                    (b"host", host_header.encode("utf-8")),
                    (b"accept", b"text/html,application/xhtml+xml"),
                ],
                extensions={"timeout": timeouts},
            )
            resp = pool.handle_request(req)
            if resp.status in _REDIRECTS:
                location = None
                for name, value in resp.headers:
                    if name.decode("latin-1").lower() == "location":
                        location = value.decode("latin-1")
                        break
                if not location:
                    raise ValueError("redirect without location")
                current = assert_public_http_url(urljoin(current, location))
                continue
            if resp.status >= 400:
                raise ValueError(f"fetch failed with status {resp.status}")
            return _read_text(resp)
        finally:
            pool.close()
    raise ValueError("too many redirects")
