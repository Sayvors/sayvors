"""Reply / hide / delete on the tenant's own comments, and the inbox read.

The write endpoints ride the same encrypted connection token as every other
IG call, scope rows to the tenant through the channel join, persist what
happened (a failed reply is a failed ROW, not just a 502), and fan out to
realtime. The inbox read never touches Graph — it is served from rows the
webhook pipeline stored.
"""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

from conftest import TEST_SESSION
from tests.test_instagram_read_cache import TENANT, _ig, _seed


@pytest.fixture
def _realtime_captured(monkeypatch):
    captured: list[tuple[str, dict]] = []
    import app.modules.channels.realtime as realtime

    async def _capture(tenant_id: str, event: dict) -> None:
        captured.append((tenant_id, event))

    monkeypatch.setattr(realtime, "publish_inbox_event", _capture)
    return captured


async def _make_channel(db, ig: str) -> str:
    from app.modules.channels.models import Channel
    import uuid

    channel_id = str(uuid.uuid4())
    db.add(Channel(
        id=channel_id,
        user_id=TENANT,
        platform="instagram",
        platform_user_id=ig,
        display_name="sayvors",
        status="active",
    ))
    await db.commit()
    return channel_id


async def _add_comment(db, channel_id: str, comment_id: str, text: str = "hi") -> None:
    from app.modules.channels.models import ChannelComment
    import uuid

    db.add(ChannelComment(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        platform_comment_id=comment_id,
        media_id="media-1",
        direction="inbound",
        content=text,
        author_id="igsid-77",
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
    ig = _ig()
    await _seed(db, ig)
    channel_id = await _make_channel(db, ig)
    await _add_comment(db, channel_id, "c-in", "first!")
    await _add_comment(db, channel_id, "c-out", "second!")

    res = client.get(f"/api/v1/meta/instagram/{ig}/comments")

    assert res.status_code == 200
    body = res.json()
    # Both rows land in the same clock tick — order between them is
    # created_at, so here only membership and shape are asserted.
    assert {c["comment_id"] for c in body["comments"]} == {"c-in", "c-out"}
    first = body["comments"][0]
    assert first["author_name"] == "fan_one"
    assert first["media_id"] == "media-1"


async def test_inbox_read_is_tenant_scoped(db, client):
    # A different tenant's (here: nonexistent) asset id is a 404, never
    # a cross-tenant read.
    res = client.get("/api/v1/meta/instagram/no-such-ig/comments")
    assert res.status_code == 404


async def test_reply_sends_stores_and_publishes(db, client, monkeypatch, _realtime_captured):
    ig = _ig()
    await _seed(db, ig)
    channel_id = await _make_channel(db, ig)
    await _add_comment(db, channel_id, "c-target")
    monkeypatch.setattr(
        InstagramAdapter, "reply_to_comment",
        AsyncMock(return_value="reply-9"),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/comments/c-target/replies",
        json={"message": "Thanks so much!"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["comment_id"] == "reply-9"
    assert body["parent_comment_id"] == "c-target"
    assert body["direction"] == "outbound"
    assert body["status"] == "sent"
    assert body["media_id"] == "media-1", "thread context inherited"
    assert InstagramAdapter.reply_to_comment.await_count == 1

    tenant_id, ev = _realtime_captured[-1]
    assert tenant_id == TENANT
    assert ev["type"] == "comment" and ev["direction"] == "outbound"


async def test_failed_reply_is_a_failed_row_and_a_502(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    channel_id = await _make_channel(db, ig)
    await _add_comment(db, channel_id, "c-target")
    monkeypatch.setattr(
        InstagramAdapter, "reply_to_comment",
        AsyncMock(side_effect=MetaAPIError("graph down", 500)),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/comments/c-target/replies",
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
    ig = _ig()
    await _seed(db, ig)
    channel_id = await _make_channel(db, ig)
    await _add_comment(db, channel_id, "c-hide")
    monkeypatch.setattr(
        InstagramAdapter, "set_comment_hidden", AsyncMock(return_value=True)
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/comments/c-hide/hide",
        json={"hidden": True},
    )

    assert res.status_code == 200
    assert res.json()["hidden"] is True
    row = await _row("c-hide")
    assert row.hidden is True
    assert _realtime_captured[-1][1]["type"] == "comment_updated"


async def test_delete_marks_deleted_at(db, client, monkeypatch, _realtime_captured):
    ig = _ig()
    await _seed(db, ig)
    channel_id = await _make_channel(db, ig)
    await _add_comment(db, channel_id, "c-del")
    monkeypatch.setattr(
        InstagramAdapter, "delete_comment", AsyncMock(return_value=True)
    )

    res = client.delete(f"/api/v1/meta/instagram/{ig}/comments/c-del")

    assert res.status_code == 200
    row = await _row("c-del")
    assert row.deleted_at is not None, "history kept, state recorded"
    assert _realtime_captured[-1][1]["type"] == "comment_deleted"


async def test_writes_without_a_token_are_403_not_500(db, client, monkeypatch):
    from app.modules.channels.meta.models import MetaConnection

    ig = _ig()
    await _seed(db, ig)
    # Null the seeded token: one connection per (tenant, provider).
    from sqlalchemy import select as _sel

    async with TEST_SESSION() as session:
        conn = (
            await session.execute(
                _sel(MetaConnection).where(MetaConnection.tenant_id == TENANT)
            )
        ).scalar_one()
        conn.access_token_encrypted = None
        await session.commit()

    monkeypatch.setattr(
        InstagramAdapter, "reply_to_comment", AsyncMock(return_value="x")
    )
    res = client.post(
        f"/api/v1/meta/instagram/{ig}/comments/c-1/replies",
        json={"message": "hi"},
    )
    assert res.status_code == 403
