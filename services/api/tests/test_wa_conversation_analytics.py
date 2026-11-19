"""WA-9: Meta-side conversation analytics, best-effort and bounded."""
import pytest

from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_adapter_flattens_meta_datapoints():
    adapter = WhatsAppAdapter.__new__(WhatsAppAdapter)
    calls = []

    async def _graph(method, path, token, **kwargs):
        calls.append((method, path, kwargs["params"]))
        return _Response({"data": [
            {"data_points": [
                {"start": "2026-11-01T00:00:00+0000", "conversation_type": "USER_INITIATED",
                 "direction": "INBOUND", "count": 3},
                {"start": "2026-11-02T00:00:00+0000", "conversation_type": "BUSINESS_INITIATED",
                 "direction": "OUTBOUND", "count": 2},
            ]}
        ]})

    adapter._graph = _graph
    import asyncio

    result = asyncio.run(adapter.get_conversation_analytics(
        "phone-1", "token", start="2026-11-01", end="2026-11-02"
    ))
    assert result["total"] == 5
    assert len(result["points"]) == 2
    assert result["points"][0]["date"] == "2026-11-01"
    assert calls[0][1] == "/phone-1/analytics"
    assert calls[0][2]["metric"] == "CONVERSATION_ANALYTICS"


def test_adapter_handles_empty_meta_data():
    adapter = WhatsAppAdapter.__new__(WhatsAppAdapter)

    async def _graph(*args, **kwargs):
        return _Response({"data": []})

    adapter._graph = _graph
    import asyncio

    result = asyncio.run(adapter.get_conversation_analytics(
        "phone-1", "token", start="2026-11-01", end="2026-11-02"
    ))
    assert result == {"points": [], "total": 0}


@pytest.mark.asyncio
async def test_endpoint_returns_provider_error_safely(client, monkeypatch):
    import app.modules.channels.meta.router as meta_router

    async def _asset(*args, **kwargs):
        return None, "token"

    class _Failing:
        async def get_conversation_analytics(self, *args, **kwargs):
            raise RuntimeError("Graph rejected: internal-secret-host")

    monkeypatch.setattr(meta_router, "_whatsapp_asset_and_token", _asset)
    monkeypatch.setattr(meta_router._service, "get_adapter", lambda provider: _Failing())

    response = client.get("/api/v1/meta/whatsapp/phone-1/analytics?days=7")
    assert response.status_code == 502
    assert "internal-secret-host" not in response.text
