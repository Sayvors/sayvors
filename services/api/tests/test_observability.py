"""Real Sentry transport canaries for credential-bearing provider URLs."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app import observability

OAUTH_URL = (
    "https://graph.facebook.com/v26.0/oauth/access_token"
    "?client_secret=fake-client-secret&fb_exchange_token=fake-fb-exchange-token"
)
SAFE_OAUTH_URL = "https://graph.facebook.com/v26.0/oauth/access_token"


class _CaptureTransport(Transport):
    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            if item.type in {"event", "transaction"}:
                self.events.append(item.payload.json)


@pytest.fixture
def sentry_canary(monkeypatch):
    transport = _CaptureTransport()
    real_init = sentry_sdk.init

    def init_with_capture(**kwargs):
        kwargs.update(
            transport=transport,
            default_integrations=False,
            traces_sample_rate=1.0,
        )
        return real_init(**kwargs)

    monkeypatch.setattr(observability.settings, "GLITCHTIP_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(sentry_sdk, "init", init_with_capture)
    assert observability.init_observability("test") is True
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()


@pytest.fixture
def sentry_default_canary(monkeypatch):
    transport = _CaptureTransport()
    real_init = sentry_sdk.init

    def init_with_capture(**kwargs):
        kwargs.update(transport=transport, traces_sample_rate=1.0)
        return real_init(**kwargs)

    monkeypatch.setattr(observability.settings, "GLITCHTIP_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(sentry_sdk, "init", init_with_capture)
    assert observability.init_observability("test") is True
    try:
        yield transport
    finally:
        sentry_sdk.get_client().close()


def _assert_secrets_removed(event: dict) -> None:
    payload = json.dumps(event)
    assert "fake-client-secret" not in payload
    assert "fake-fb-exchange-token" not in payload
    assert SAFE_OAUTH_URL in payload


def test_sentry_hooks_redact_standalone_query_fields():
    event = {
        "contexts": {
            "trace": {
                "data": {
                    "http.query": "input_token=fake-input-token&fields=id",
                    "url.query": "client_secret=fake-client-secret",
                }
            }
        },
        "extra": {"detail": "input_token=fake-input-token"},
    }

    for hook in (observability._before_send, observability._before_send_transaction):
        scrubbed = hook(event, {})
        payload = json.dumps(scrubbed)
        assert "fake-input-token" not in payload
        assert "fake-client-secret" not in payload
        assert "[redacted]" in payload


def test_default_httpx_integration_cannot_capture_debug_token_query(sentry_default_canary):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib callback name
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, _format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sentry_sdk.start_transaction(name="debug-token", op="http.client"):
            response = httpx.get(
                f"http://127.0.0.1:{server.server_port}/debug_token?input_token=fake-input-token",
                trust_env=False,
                timeout=5,
            )
            response.raise_for_status()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    sentry_sdk.flush()

    assert len(sentry_default_canary.events) == 1
    payload = json.dumps(sentry_default_canary.events[0])
    assert '"http.query"' in payload or '"url.query"' in payload
    assert "fake-input-token" not in payload


def test_init_omits_profiles_option_on_sentry_v3(monkeypatch):
    captured = {}

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.settings, "GLITCHTIP_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(observability, "_SENTRY_MAJOR", 3)
    monkeypatch.setattr(sentry_sdk, "init", fake_init)

    assert observability.init_observability("test") is True
    assert "profiles_sample_rate" not in captured
    assert captured["traces_sample_rate"] == 0.1


def test_sentry_error_canary_strips_oauth_url_queries(sentry_canary):
    with sentry_sdk.new_scope() as scope:
        scope.set_context("provider", {
            "url": OAUTH_URL,
            "nested": [{"request_url": OAUTH_URL}],
            "authorization": "Bearer fake-header-secret",
        })
        sentry_sdk.capture_exception(RuntimeError(f"OAuth failed: {OAUTH_URL}"))
    sentry_sdk.flush()

    assert len(sentry_canary.events) == 1
    _assert_secrets_removed(sentry_canary.events[0])
    assert "fake-header-secret" not in json.dumps(sentry_canary.events[0])


def test_sentry_transaction_canary_strips_oauth_url_queries(sentry_canary):
    with sentry_sdk.start_transaction(name="oauth-exchange", op="http.client") as transaction:
        transaction.set_data("url", OAUTH_URL)
        transaction.set_data("nested", {"exchange_url": OAUTH_URL})
    sentry_sdk.flush()

    assert len(sentry_canary.events) == 1
    assert sentry_canary.events[0]["transaction"] == "oauth-exchange"
    _assert_secrets_removed(sentry_canary.events[0])
