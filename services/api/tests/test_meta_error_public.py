"""Meta errors keep the raw provider text in logs, never in HTTP responses.

LAUNCH-S10 Phase 1 sanitized 502 paths, but the connect/asset endpoints still
returned ``str(MetaAPIError)`` — and several constructors embed raw
``resp.text`` from the provider. The error now carries a separate ``public``
message that routers use.
"""
import pytest

from app.modules.channels.meta.providers.base import MetaAPIError, MetaProviderAdapter


def test_curated_error_keeps_its_message_as_public():
    err = MetaAPIError("WhatsApp delivery is temporarily paced", 429)
    assert err.public == "WhatsApp delivery is temporarily paced"


def test_raw_upstream_text_is_not_the_public_message():
    err = MetaAPIError(
        'Graph call failed: {"error":{"message":"secret token abc123"}}',
        400,
        public="The provider rejected the request. Check the connection and try again.",
    )
    assert "abc123" in str(err)  # logs keep the evidence
    assert "abc123" not in err.public
    assert err.status_code == 400


class _FakeHttp:
    def __init__(self, response):
        self.response = response

    async def request(self, method, url, **kwargs):
        return self.response


class _FakeResponse:
    status_code = 400
    text = '{"error":{"message":"upstream-secret-xyz","type":"OAuthException"}}'


class _Provider(MetaProviderAdapter):
    def __init__(self):
        self._http = _FakeHttp(_FakeResponse())

    # Abstract methods are never called in this test.
    async def exchange_code(self, code, redirect_uri=None):
        raise NotImplementedError

    async def discover_assets(self, credentials):
        raise NotImplementedError

    async def validate_connection(self, connection, credentials):
        raise NotImplementedError

    def build_auth_entry(self, state):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_graph_failure_hides_raw_body_from_clients():
    with pytest.raises(MetaAPIError) as caught:
        await _Provider()._graph("GET", "/me", "token")
    err = caught.value
    assert "upstream-secret-xyz" in str(err)
    assert "upstream-secret-xyz" not in err.public
    assert err.public == "The provider rejected the request. Check the connection and try again."
