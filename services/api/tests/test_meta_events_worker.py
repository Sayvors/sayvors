"""Contract tests for the meta events worker.

The worker replaced the Kafka consumer and routed events to the same
handlers, but called every one of them with a single argument while they all
take `(event, data)`. That is a TypeError on the first event of every type,
so the entire inbound pipeline -- storing messages, capturing leads, answering
with the AI -- failed while every healthcheck stayed green. Nothing else in the
suite exercised this file, so it deployed.

Two things are pinned here:

  * every handler is called with the arity its signature declares
  * the envelope is split into `(event, data)` the same way
    consumer._process_message splits it

If a handler signature changes, this fails instead of the pipeline.
"""

import inspect

import pytest

from app.modules.channels.meta import consumer as meta_consumer
from app.modules.channels.meta import meta_events_worker as worker

ROUTED_HANDLERS = [
    "_handle_message_received",
    "_handle_message_status",
    "_handle_message_history",
    "_handle_message_echo",
    "_handle_smb_contacts",
    "_handle_connection_disconnect",
    "_handle_instagram_echo",
    "_handle_instagram_message",
    "_handle_instagram_comment",
    "_handle_facebook_comment",
]


@pytest.mark.parametrize("name", ROUTED_HANDLERS)
def test_worker_imports_the_handler_it_calls(name):
    """A renamed or removed handler must fail here, not at 3am in prod."""
    assert hasattr(worker, name), f"worker calls {name} but does not import it"


@pytest.mark.parametrize("name", ROUTED_HANDLERS)
def test_every_handler_takes_event_and_data(name):
    """Guards the exact bug: arity drift between the worker and the handlers."""
    sig = inspect.signature(getattr(meta_consumer, name))
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    names = [p.name for p in positional]
    assert names[:2] == ["event", "data"], (
        f"{name} takes {names}; the worker routes with "
        "(event, data) where data is the envelope's nested payload"
    )


def _envelope(provider: str, event_type: str, data: dict) -> dict:
    """The shape webhooks/router.py writes into event_outbox.payload."""
    return {
        "event_id": "e1",
        "tenant_id": "t1",
        "connection_id": "c1",
        "provider": provider,
        "event_type": event_type,
        "external_asset_id": "123",
        "external_event_id": "wamid.1",
        "occurred_at": "2026-10-14T00:00:00Z",
        "payload": data,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,event_type,attr",
    [
        ("whatsapp", "message.received", "_handle_message_received"),
        ("whatsapp", "message.status", "_handle_message_status"),
        ("whatsapp", "message.history", "_handle_message_history"),
        ("whatsapp", "message.echo", "_handle_message_echo"),
        ("whatsapp", "smb.contacts", "_handle_smb_contacts"),
        ("whatsapp", "connection.disconnect", "_handle_connection_disconnect"),
        ("instagram", "comment.received", "_handle_instagram_comment"),
        ("facebook", "comment.received", "_handle_facebook_comment"),
    ],
)
async def test_event_is_split_into_envelope_and_nested_payload(
    monkeypatch, provider, event_type, attr
):
    """The handler must receive the envelope AND the nested provider data."""
    seen = {}

    async def spy(event, data):
        seen["event"] = event
        seen["data"] = data

    monkeypatch.setattr(worker, attr, spy)

    data = {"from": "9665", "text": "hello"}
    row = {
        "id": "evt-1",
        "event_type": f"meta.{event_type}",
        "topic": "meta-events",
        "attempts": 0,
        "next_retry_at": None,
        "payload": _envelope(provider, event_type, data),
    }

    sent = []

    class FakeDB:
        async def execute(self, *a, **k):
            class R:
                async def commit(self_inner):
                    return None

            return R()

    async def mark_sent(db, event_id):
        sent.append(event_id)

    monkeypatch.setattr(worker, "_mark_event_sent", mark_sent)

    assert await worker._process_event(FakeDB(), row) is True
    assert seen["event"]["provider"] == provider
    assert seen["data"] == data, "the nested payload is what the handlers read"
    assert sent == ["evt-1"]


@pytest.mark.asyncio
async def test_instagram_echo_is_history_not_an_auto_reply(monkeypatch):
    """An echo is the merchant's own reply; auto-answering it would loop."""
    routed = []

    async def echo(event, data):
        routed.append("echo")

    async def message(event, data):
        routed.append("message")

    monkeypatch.setattr(worker, "_handle_instagram_echo", echo)
    monkeypatch.setattr(worker, "_handle_instagram_message", message)

    class FakeDB:
        async def execute(self, *a, **k):
            class R:
                async def commit(self_inner):
                    return None

            return R()

    monkeypatch.setattr(
        worker, "_mark_event_sent", lambda db, eid: _noop()
    )

    async def _noop():
        return None

    def row(data):
        return {
            "id": "evt-2",
            "event_type": "meta.message.received",
            "topic": "meta-events",
            "attempts": 0,
            "next_retry_at": None,
            "payload": _envelope("instagram", "message.received", data),
        }

    await worker._process_event(FakeDB(), row({"raw": {"message": {"is_echo": True}}}))
    await worker._process_event(FakeDB(), row({"raw": {"message": {"is_echo": False}}}))

    assert routed == ["echo", "message"]