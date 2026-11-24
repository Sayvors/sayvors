"""Proxy routing for the free Google endpoints.

Routes are sticky per place/query so one scrape keeps one IP (BOQ pagination
tokens are IP-bound), rotate to another proxy when one is blocked, and never
fall back to the server's own IP once proxies are configured.
"""
import httpx
import pytest

from app.config import settings
from app.modules.benchmark import net

P1 = "http://u:p@proxy1.example:8000"
P2 = "http://proxy2.example:8000"
P3 = "http://proxy3.example:8000"


@pytest.fixture(autouse=True)
def _clean_pool(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", "")
    monkeypatch.setattr(net, "_state", {})
    monkeypatch.setattr(net, "_now", lambda: 1000.0)
    yield


def test_no_proxies_configured_means_one_direct_route():
    assert net.routes_for("anything") == [None]


def test_blank_and_whitespace_entries_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", f"  {P1} , ,{P2},  ")

    assert sorted(net.routes_for("k")) == sorted([P1, P2])


def test_route_order_is_sticky_per_key_and_covers_every_proxy(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", f"{P1},{P2},{P3}")

    first = net.routes_for("place-a")
    again = net.routes_for("place-a")

    assert first == again, "the same place must keep the same first route"
    assert sorted(first) == sorted([P1, P2, P3])
    assert None not in first, "direct egress must not be used once proxies exist"
    # Different places spread across the pool rather than piling onto one proxy.
    firsts = {net.routes_for(f"place-{i}")[0] for i in range(8)}
    assert len(firsts) >= 2


def test_a_blocked_route_goes_into_cooldown_and_is_skipped(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", f"{P1},{P2},{P3}")

    net.note_result(P2, ok=False)

    routes = net.routes_for("some-other-place")
    assert P2 not in routes
    assert sorted(routes) == sorted([P1, P3])


def test_cooldown_expires_and_the_route_returns(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", f"{P1},{P2}")
    net.note_result(P1, ok=False)
    assert P1 not in net.routes_for("x")

    clock = {"now": 1000.0}
    monkeypatch.setattr(net, "_now", lambda: clock["now"])
    clock["now"] = 1000.0 + net.PROXY_COOLDOWN_SECONDS + 1

    assert P1 in net.routes_for("x")


def test_a_success_clears_the_failure_count(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", P1)
    net.note_result(P1, ok=False)
    net.note_result(P1, ok=True)

    assert net.routes_for("x") == [P1]


def test_if_every_route_is_cooling_down_all_are_offered(monkeypatch):
    """Better to retry a cooling proxy than to scrape nothing at all."""
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", f"{P1},{P2}")
    net.note_result(P1, ok=False)
    net.note_result(P2, ok=False)

    assert sorted(net.routes_for("x")) == sorted([P1, P2])


def test_client_for_route_applies_the_proxy(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(net.httpx, "AsyncClient", FakeClient)

    net.client_for(P1, timeout=5.0)
    assert seen["proxy"] == P1
    assert seen["timeout"] == 5.0

    seen.clear()
    net.client_for(None, timeout=5.0)
    assert "proxy" not in seen


def test_invalid_proxy_entries_are_dropped(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_SCRAPER_PROXIES", "not-a-url,ftp://x")

    assert net.routes_for("k") == [None]
