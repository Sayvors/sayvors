"""Pin the Meta Message Templates API shapes used for authoring.

These are the calls the dashboard makes; a wrong path or query parameter is a
production-only 404/400 that unit tests around the service layer would miss.
"""
from types import SimpleNamespace

import pytest

from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter


def _response(payload):
    return SimpleNamespace(content=b"{}", json=lambda: payload)


async def _capture(adapter, payload):
    calls: list[tuple] = []

    async def fake_graph(method, path, token, **kwargs):
        calls.append((method, path, token, kwargs))
        return _response(payload)

    adapter._graph = fake_graph
    return calls


@pytest.mark.asyncio
async def test_create_posts_to_the_waba_with_a_body_and_samples():
    adapter = WhatsAppAdapter()
    calls = await _capture(adapter, {"id": "t-1", "status": "PENDING"})
    try:
        result = await adapter.create_template(
            "waba-1", "tok",
            name="order_ready", language="en_US", category="utility",
            body="Order {{1}} is ready.", examples=["A-1"],
        )
    finally:
        await adapter.close()

    assert result["id"] == "t-1"
    method, path, token, kwargs = calls[0]
    assert (method, path, token) == ("POST", "/waba-1/message_templates", "tok")
    assert kwargs["json"] == {
        "name": "order_ready",
        "language": "en_US",
        "category": "UTILITY",
        "components": [{
            "type": "BODY",
            "text": "Order {{1}} is ready.",
            "example": {"body_text": ["A-1"]},
        }],
        "allow_category_change": True,
    }


@pytest.mark.asyncio
async def test_update_posts_to_the_template_id():
    adapter = WhatsAppAdapter()
    calls = await _capture(adapter, {"status": "PENDING"})
    try:
        await adapter.update_template(
            "t-1", "tok", category="marketing",
            body="New body", examples=[],
        )
    finally:
        await adapter.close()

    method, path, token, kwargs = calls[0]
    assert (method, path, token) == ("POST", "/t-1", "tok")
    assert kwargs["json"] == {
        "category": "MARKETING",
        "components": [{"type": "BODY", "text": "New body"}],
    }


@pytest.mark.asyncio
async def test_delete_targets_the_waba_with_name_and_hsm_id():
    adapter = WhatsAppAdapter()
    calls = await _capture(adapter, {"success": True})
    try:
        await adapter.delete_template(
            "tok", template_id="t-1", waba_id="waba-1", name="order_ready",
        )
    finally:
        await adapter.close()

    method, path, token, kwargs = calls[0]
    assert (method, path, token) == (
        "DELETE", "/waba-1/message_templates", "tok",
    )
    assert kwargs["params"] == {"name": "order_ready", "hsm_id": "t-1"}
