"""WhatsApp interactive messages: buttons, list menus, CTA links.

Two callers share the same validators: the AI reply path (a `CHOICES:` line
in the model output) and the inbox API. Meta rejects a bad payload with a
hard error, and that error would cost the customer their reply, so every
limit is enforced before the request leaves the process.
"""
import pytest

from app.modules.channels.meta.interactive import (
    build_buttons,
    build_cta_url,
    build_list,
    readable_content,
    split_choices,
)


# ── the AI directive ─────────────────────────────────────────────────


def test_choices_line_is_split_off_the_reply():
    text, choices = split_choices(
        'Sure — happy to help.\n\nCHOICES: ["Pricing", "Book a demo", "Talk to a human"]'
    )
    assert text == "Sure — happy to help."
    assert choices == ["Pricing", "Book a demo", "Talk to a human"]


def test_a_bad_choices_line_never_eats_the_reply():
    raw = 'Here is the answer.\nCHOICES: not-json'
    assert split_choices(raw) == (raw, [])


def test_single_or_too_many_choices_are_dropped():
    assert split_choices('Hi\nCHOICES: ["One"]') == ('Hi', [])
    assert split_choices('Hi\nCHOICES: ["A", "B", "C", "D"]') == ('Hi', [])


def test_duplicate_choice_labels_are_dropped():
    assert split_choices('Hi\nCHOICES: ["Book", "book"]') == ('Hi', [])


def test_prose_mentioning_choices_is_left_alone():
    text = "You have two CHOICES: pay now or later."
    assert split_choices(text) == (text, [])


# ── payload builders ─────────────────────────────────────────────────


def test_buttons_payload_shape():
    payload = build_buttons("How can I help?", ["Pricing", "Book a demo"])
    assert payload["type"] == "button"
    assert payload["body"]["text"] == "How can I help?"
    buttons = payload["action"]["buttons"]
    assert [b["reply"]["title"] for b in buttons] == ["Pricing", "Book a demo"]
    assert [b["reply"]["id"] for b in buttons] == ["choice_1", "choice_2"]
    assert all(b["type"] == "reply" for b in buttons)


def test_buttons_reject_more_than_three_or_long_titles():
    with pytest.raises(ValueError):
        build_buttons("x", ["A", "B", "C", "D"])
    with pytest.raises(ValueError):
        build_buttons("x", ["This title is far too long for a button"])
    with pytest.raises(ValueError):
        build_buttons("", ["A"])


def test_list_payload_shape_and_limits():
    payload = build_list(
        "Pick a service",
        "Choose",
        [{
            "title": "Websites",
            "rows": [
                {"id": "web", "title": "Website", "description": "5-10 pages"},
                {"id": "shop", "title": "Online store"},
            ],
        }],
    )
    assert payload["type"] == "list"
    assert payload["action"]["button"] == "Choose"
    rows = payload["action"]["sections"][0]["rows"]
    assert [r["id"] for r in rows] == ["web", "shop"]
    assert rows[0]["description"] == "5-10 pages"

    too_many = [{"title": "S", "rows": [
        {"id": f"r{i}", "title": f"Row {i}"} for i in range(11)
    ]}]
    with pytest.raises(ValueError):
        build_list("x", "Choose", too_many)


def test_cta_url_requires_an_absolute_http_url():
    payload = build_cta_url("See the full menu", "Open menu", "https://example.com/menu")
    assert payload["type"] == "cta_url"
    assert payload["action"]["parameters"]["url"] == "https://example.com/menu"
    with pytest.raises(ValueError):
        build_cta_url("x", "Open", "/menu")
    with pytest.raises(ValueError):
        build_cta_url("x", "A label that is definitely too long", "https://x.com")


def test_readable_content_is_what_the_inbox_shows():
    text = readable_content("How can I help?", ["Pricing", "Book a demo"])
    assert text == "How can I help?\n\nOptions: Pricing · Book a demo"


# ── adapter payload ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adapter_posts_an_interactive_message(monkeypatch):
    from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter

    captured: dict = {}

    class _Resp:
        def json(self):
            return {"messages": [{"id": "wamid-int-1"}]}

    async def _graph(self, method, path, token, **kwargs):
        captured.update({"method": method, "path": path, "token": token, **kwargs})
        return _Resp()

    monkeypatch.setattr(WhatsAppAdapter, "_graph", _graph)

    wamid = await WhatsAppAdapter().send_interactive_buttons(
        "phone-1", "tok", "+966500001111", "How can I help?",
        ["Pricing", "Book a demo"],
    )

    assert wamid == "wamid-int-1"
    assert captured["path"] == "/phone-1/messages"
    body = captured["json"]
    assert body["type"] == "interactive"
    assert body["interactive"]["type"] == "button"
    assert body["interactive"]["action"]["buttons"][0]["reply"]["title"] == "Pricing"


# ── service: persistence + ownership ─────────────────────────────────


@pytest.mark.asyncio
async def test_interactive_send_is_recorded_as_a_human_outbound(db, user_id, monkeypatch):
    from types import SimpleNamespace
    import uuid

    from app.modules.channels import service
    from app.modules.channels.models import Channel, ChannelMessage
    from app.modules.channels.service import decrypt_message_content

    channel_id = f"wa-chan-{uuid.uuid4().hex[:8]}"
    db.add(Channel(
        id=channel_id,
        user_id=user_id,
        platform="whatsapp",
        platform_user_id="phone-1",
        display_name="WhatsApp",
        status="active",
    ))
    await db.commit()

    async def _dispatch(db_, user_, channel_, to, kind, payload):
        assert kind == "buttons"
        assert to == "+966500001111"
        return "wamid-int-2", ""

    monkeypatch.setattr(service, "_dispatch_whatsapp_interactive", _dispatch)

    user = SimpleNamespace(id=user_id, tenant_id=None)
    msg = await service.send_interactive_message(
        channel_id,
        contact_phone="+966500001111",
        kind="buttons",
        payload={"body": "How can I help?", "buttons": ["Pricing", "Book a demo"]},
        user=user,
        db=db,
    )

    assert msg.status == "sent"
    assert msg.content_type == "interactive"
    assert msg.handled_by == "human"
    stored = await db.get(ChannelMessage, msg.id)
    assert "Options: Pricing · Book a demo" in decrypt_message_content(stored.content)


@pytest.mark.asyncio
async def test_interactive_send_rejects_a_non_whatsapp_channel(db, channel_id, user_id):
    """The google_reviews fixture channel is not WhatsApp."""
    from types import SimpleNamespace

    from app.modules.channels import service

    user = SimpleNamespace(id=user_id, tenant_id=None)
    with pytest.raises(ValueError, match="only available on WhatsApp"):
        await service.send_interactive_message(
            channel_id,
            contact_phone="+966500001111",
            kind="buttons",
            payload={"body": "x", "buttons": ["A"]},
            user=user,
            db=db,
        )


# ── API surface ──────────────────────────────────────────────────────


def test_api_rejects_an_unknown_kind(client):
    res = client.post(
        "/api/v1/channels/any/interactive",
        json={"contact_phone": "+1", "kind": "carousel", "body": "x"},
    )
    assert res.status_code == 422
