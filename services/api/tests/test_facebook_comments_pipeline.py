"""Comments on the Page's own posts land in channel_comments.

Same inbox contract as Instagram, FB field shapes: the post rides post_id,
the author's display name rides from.name, threading rides parent_id, and
the platform clock rides the envelope's occurred_at. Kafka replays never
twin a row; an edited redelivery updates the text; unknown assets are
dropped. Nothing here auto-replies — public answers go out from the hub,
by a human.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.modules.channels.meta.consumer import (
    _handle_facebook_comment,
    _platform_timestamp,
)
from app.modules.channels.models import ChannelComment
# Top-level import: `tests.conftest` would re-execute the module and build
# a SECOND empty in-memory engine (no tests/__init__.py — namespace trap).
from conftest import TEST_SESSION

pytestmark = pytest.mark.asyncio

from tests.test_facebook_reads import TENANT, _fb, _seed


@pytest.fixture(autouse=True)
def _handler_db(monkeypatch):
    """Consumer handlers open their own session — point it at the shared
    in-memory test engine the `db` fixture seeds."""
    import app.modules.channels.meta.consumer as consumer

    monkeypatch.setattr(consumer, "async_session", TEST_SESSION)


@pytest.fixture
def _realtime_captured(monkeypatch):
    captured: list[tuple[str, dict]] = []
    import app.modules.channels.realtime as realtime

    async def _capture(tenant_id: str, event: dict) -> None:
        captured.append((tenant_id, event))

    monkeypatch.setattr(realtime, "publish_inbox_event", _capture)
    return captured


def _event(pid: str, comment_id: str, text: str = "love this!") -> tuple[dict, dict]:
    event = {
        "external_asset_id": pid,
        "external_event_id": comment_id,
        "event_type": "comment.received",
        "occurred_at": "2026-10-10T09:00:00+00:00",
    }
    data = {
        "post_id": f"{pid}_101",
        "message": text,
        "from": {"id": "fbuser-77", "name": "Fan One"},
        "parent_id": None,
    }
    return event, data


async def _row(platform_comment_id: str) -> ChannelComment | None:
    async with TEST_SESSION() as session:
        return (
            await session.execute(
                select(ChannelComment).where(
                    ChannelComment.platform_comment_id == platform_comment_id,
                )
            )
        ).scalar_one_or_none()


async def test_comment_is_stored_with_platform_truth(db, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    event, data = _event(pid, "c-1")

    import app.modules.channels.meta.consumer as _c

    assert _c.async_session is TEST_SESSION
    await _handle_facebook_comment(event, data)

    row = await _row("c-1")
    assert row is not None
    assert row.direction == "inbound"
    assert row.content == "love this!"
    assert row.author_id == "fbuser-77"
    assert row.author_name == "Fan One", "FB carries a name, not a username"
    assert row.media_id == f"{pid}_101", "the FB post id rides media_id"
    assert row.status == "received"
    assert row.deleted_at is None
    # The envelope's occurred_at is the platform clock. SQLite round-trips
    # datetimes naive — compare the wall-clock value.
    assert row.platform_timestamp is not None
    assert row.platform_timestamp.replace(tzinfo=None) == datetime(
        2026, 10, 10, 9, 0
    )

    assert len(_realtime_captured) == 1
    tenant_id, ev = _realtime_captured[0]
    assert tenant_id == TENANT
    assert ev["type"] == "comment"
    assert ev["platform"] == "facebook"
    assert ev["media_id"] == f"{pid}_101"


async def test_reply_threads_via_parent_id(db, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    event, data = _event(pid, "c-reply")
    data["parent_id"] = "c-root"

    await _handle_facebook_comment(event, data)

    row = await _row("c-reply")
    assert row is not None
    assert row.parent_platform_comment_id == "c-root"


async def test_kafka_replay_does_not_twin(db, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    event, data = _event(pid, "c-2")

    await _handle_facebook_comment(event, data)
    await _handle_facebook_comment(event, data)

    rows = await _row("c-2")
    assert rows is not None
    assert len(_realtime_captured) == 1, "replay must not re-publish"


async def test_edited_redelivery_updates_text(db, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    event, data = _event(pid, "c-3")

    await _handle_facebook_comment(event, data)
    # Same platform id, new text — Meta's "edited" redelivery.
    data["message"] = "love this! (edited)"
    await _handle_facebook_comment(event, data)

    row = await _row("c-3")
    assert row is not None
    assert row.content == "love this! (edited)"
    assert len(_realtime_captured) == 2
    assert _realtime_captured[1][1]["type"] == "comment_updated"
    assert _realtime_captured[1][1]["platform"] == "facebook"
    assert _realtime_captured[1][1]["content"] == "love this! (edited)"


async def test_comment_from_unknown_asset_is_dropped(db, _realtime_captured):
    event, data = _event(_fb(), "c-4")

    await _handle_facebook_comment(event, data)

    assert await _row("c-4") is None
    assert _realtime_captured == []
