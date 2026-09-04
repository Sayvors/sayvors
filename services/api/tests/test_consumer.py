"""Consumer event-guard tests (no DB)."""
import asyncio

from app.modules.analytics.consumer import _process_message


def test_process_message_handles_malformed():
    asyncio.run(_process_message(None))
    asyncio.run(_process_message(b"not json"))
    asyncio.run(_process_message(b'{"event_type": "unknown.thing", "payload": {}}'))


def test_process_message_handles_empty():
    asyncio.run(_process_message(b'{"event_type": "review.enriched", "payload": {}}'))