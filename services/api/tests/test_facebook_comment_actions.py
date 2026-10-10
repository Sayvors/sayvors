"""Reply / hide / delete on the Page's own comments, and the inbox read.

Writes ride the page token stored on the asset row, scope rows to the
tenant through the channel join, persist what happened (a failed reply is
a failed ROW, not just a 502), and fan out to realtime with
platform "facebook". The inbox read never touches Graph — it is served
from rows the webhook pipeline stored.
"""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.facebook import FacebookAdapter

pytestmark = pytest.mark.asyncio

from conftest import TEST_SESSION
from tests.test_facebook_reads import TENANT, _fb, _seed


@pytest.fixture
def _realtime_captured(monkeypatch):
    captured: list[tuple[str, dict]] = []
    import app.modules.channels.realtime as realtime

    async def _capture(tenant_id: str, event: dict) -> None:
        captured.append((tenant_id, event))

    monkeypatch.setattr(realtime, "publish_inbox_event", _capture)
    return captured


async def _make_channel(db, page_id: str) -> str:
    from app.modules.channels.models import Channel
    import uuid

    channel_id = str(uuid.uuid4())
    db.add(Channel(
        id=channel_id,
        user_id=TENANT,
        platform="facebook",
        platform_user_id=page_id,
        display_name="Sayvors Page",
        status="active",
    ))
    await db.commit()
    return channel_id


async def _add_comment(
    db, channel_id: str, comment_id: str, text: str = "hi",
    *, media_id: str = "media-1",
) -> None:
    from app.modules.channels.models import ChannelComment
    import uuid

    db.add(ChannelComment(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        platform_comment_id=comment_id,
        media_id=media_id,
        direction="inbound",
        content=text,
        author_id="fbuser-77",
        author_name="fan_one",
        status="received",
    ))
    await db.commit()


async def _row(comment_id: str):
    from app.modules.channels.models import ChannelComment

    async with TEST_SESSION() as session:
        return (
            await session.execute(
                select(ChannelComment).where(
                    ChannelComment.platform_comment_id == comment_id,
                )
            )
        ).scalar_one_or_none()


async def test_inbox_read_is_served_from_rows_not_graph(db, client):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-in", "first!")
    await _add_comment(db, channel_id, "c-out", "second!")

    res = client.get(f"/api/v1/meta/facebook/{pid}/comments")

    assert res.status_code == 200
    body = res.json()
    assert {c["comment_id"] for c in body["comments"]} == {"c-in", "c-out"}
    first = body["comments"][0]
    assert first["author_name"] == "fan_one"
    assert first["media_id"] == "media-1"


async def test_inbox_read_is_tenant_scoped(db, client):
    # A different tenant's (here: nonexistent) asset id is a 404, never
    # a cross-tenant read.
    res = client.get(f"/api/v1/meta/facebook/{_fb()}/comments")
    assert res.status_code == 404


async def test_inbox_filters_by_media_id(db, client):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-post-a", "on post a", media_id=f"{pid}_101")
    await _add_comment(db, channel_id, "c-post-b", "on post b", media_id=f"{pid}_202")

    res = client.get(
        f"/api/v1/meta/facebook/{pid}/comments",
        params={"media_id": f"{pid}_202"},
    )

    assert res.status_code == 200
    assert [c["comment_id"] for c in res.json()["comments"]] == ["c-post-b"]


async def test_reply_sends_stores_and_publishes(db, client, monkeypatch, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-target")
    monkeypatch.setattr(
        FacebookAdapter, "reply_to_comment",
        AsyncMock(return_value="reply-9"),
    )

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/comments/c-target/replies",
        json={"message": "Thanks so much!"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["comment_id"] == "reply-9"
    assert body["parent_comment_id"] == "c-target"
    assert body["direction"] == "outbound"
    assert body["status"] == "sent"
    assert body["media_id"] == "media-1", "thread context inherited"
    assert FacebookAdapter.reply_to_comment.await_count == 1

    tenant_id, ev = _realtime_captured[-1]
    assert tenant_id == TENANT
    assert ev["type"] == "comment" and ev["direction"] == "outbound"
    assert ev["platform"] == "facebook"


async def test_failed_reply_is_a_failed_row_and_a_502(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-target")
    monkeypatch.setattr(
        FacebookAdapter, "reply_to_comment",
        AsyncMock(side_effect=MetaAPIError("graph down", 500)),
    )

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/comments/c-target/replies",
        json={"message": "Thanks!"},
    )

    assert res.status_code == 502
    # The failed attempt must be visible in the thread, keyed by parent.
    from app.modules.channels.models import ChannelComment

    async with TEST_SESSION() as session:
        failed = (
            await session.execute(
                select(ChannelComment).where(
                    ChannelComment.parent_platform_comment_id == "c-target",
                    ChannelComment.status == "failed",
                )
            )
        ).scalar_one()
    assert "graph down" in failed.error


async def test_hide_flips_the_row(db, client, monkeypatch, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-hide")
    monkeypatch.setattr(
        FacebookAdapter, "set_comment_hidden", AsyncMock(return_value=True)
    )

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/comments/c-hide/hide",
        json={"hidden": True},
    )

    assert res.status_code == 200
    assert res.json()["hidden"] is True
    row = await _row("c-hide")
    assert row.hidden is True
    tenant_id, ev = _realtime_captured[-1]
    assert ev["type"] == "comment_updated" and ev["platform"] == "facebook"


async def test_delete_marks_deleted_at(db, client, monkeypatch, _realtime_captured):
    pid = _fb()
    await _seed(db, pid)
    channel_id = await _make_channel(db, pid)
    await _add_comment(db, channel_id, "c-del")
    monkeypatch.setattr(
        FacebookAdapter, "delete_comment", AsyncMock(return_value=True)
    )

    res = client.delete(f"/api/v1/meta/facebook/{pid}/comments/c-del")

    assert res.status_code == 200
    row = await _row("c-del")
    assert row.deleted_at is not None, "history kept, state recorded"
    assert _realtime_captured[-1][1]["type"] == "comment_deleted"


async def test_writes_without_a_page_token_are_403_not_500(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid, with_token=False)

    monkeypatch.setattr(
        FacebookAdapter, "reply_to_comment", AsyncMock(return_value="x")
    )
    res = client.post(
        f"/api/v1/meta/facebook/{pid}/comments/c-1/replies",
        json={"message": "hi"},
    )
    assert res.status_code == 403
