"""LAUNCH-B3: the Graph transport layer retries only what is provably safe.

Connect-phase failures never reached Meta, so a bounded in-place retry
cannot double-send. Once the request is on the wire (read timeout, broken
response, write error) the outcome is unknown: _graph raises
MetaAmbiguousError and the caller's taxonomy files the event ambiguous —
no HTTP-layer retry. HTTP-level 429/5xx are Meta's answers, not transport
failures, so they surface as plain MetaAPIError for caller-specific
handling and are never retried here.
"""
import httpx
import pytest

from app.modules.channels.meta.providers import base as graph_base
from app.modules.channels.meta.providers.base import (
    GRAPH_CONNECT_ATTEMPTS,
    MetaAmbiguousError,
    MetaAPIError,
    MetaTransportError,
)
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter


async def _no_sleep(_seconds):
    return None


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(graph_base.asyncio, "sleep", _no_sleep)


def _adapter(handler) -> WhatsAppAdapter:
    adapter = WhatsAppAdapter()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


async def _graph(adapter, method="GET", path="/me"):
    return await adapter._graph(method, path, token="tok")


async def test_connect_error_is_retried_and_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"id": "me"})

    resp = await _graph(_adapter(handler))

    assert calls["n"] == 2
    assert resp.status_code == 200


async def test_connect_failures_are_bounded_and_typed_transient():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("no route to host")

    adapter = _adapter(handler)

    with pytest.raises(MetaTransportError) as excinfo:
        await _graph(adapter)

    # Exactly the bounded budget — no unbounded loop, no silent give-up.
    assert calls["n"] == GRAPH_CONNECT_ATTEMPTS
    assert excinfo.value.status_code == 503
    assert isinstance(excinfo.value.__cause__, httpx.ConnectTimeout)


async def test_read_timeout_is_ambiguous_and_never_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timed out")

    adapter = _adapter(handler)

    with pytest.raises(MetaAmbiguousError) as excinfo:
        await _graph(adapter, method="POST", path="/messages")

    # The request was on the wire: one attempt, then "unknown" — a retry
    # here could double-message a customer.
    assert calls["n"] == 1
    assert "mid-flight" in str(excinfo.value)


async def test_broken_response_is_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("server disconnected without sending a response")

    with pytest.raises(MetaAmbiguousError):
        await _graph(_adapter(handler))


async def test_http_4xx_is_a_meta_answer_not_a_transport_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad token"}})

    adapter = _adapter(handler)

    with pytest.raises(MetaAPIError) as excinfo:
        await _graph(adapter)

    assert calls["n"] == 1
    assert excinfo.value.status_code == 401
    assert not isinstance(excinfo.value, MetaTransportError)


async def test_http_5xx_is_answered_once_handling_belongs_to_callers():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"error": {"message": "internal"}})

    adapter = _adapter(handler)

    with pytest.raises(MetaAPIError) as excinfo:
        await _graph(adapter)

    # Meta answered, so the transport layer stays out of it — the consumer
    # classifies 5xx as transient against its own retry budget.
    assert calls["n"] == 1
    assert excinfo.value.status_code == 500
