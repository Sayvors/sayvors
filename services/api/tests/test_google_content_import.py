"""Google content import: posts + gallery media pulled on connect.

Pins the properties that make the import safe:
  * posts and media become Sayvors rows matched by Google resource name
  * re-running does not duplicate
  * a merchant-authored draft is never overwritten by Google's copy
  * a failure never raises (content must not break connect)
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels import google_content_import as gci
from app.modules.channels.models import Channel
from app.modules.media.models import LocationMedia
from app.modules.posts.models import LocationPost


def _google_post(name="accounts/a/locations/l/localPosts/p1", **over):
    post = {
        "name": name,
        "topicType": "UPDATE",
        "state": "PUBLISHED",
        "summary": "Welcome to our store",
        "createTime": "2026-09-20T08:42:40Z",
        "media": [{"sourceUrl": "https://example.com/a.jpg"}],
        "callToAction": {"type": "LEARN_MORE", "uri": "https://example.com"},
    }
    post.update(over)
    return post


def _media_item(name="accounts/a/locations/l/media/m1", **over):
    item = {
        "name": name,
        "mediaFormat": "PHOTO",
        "locationAssociation": {"category": "EXTERIOR"},
        "googleUrl": "https://example.com/photo.jpg",
        "createTime": "2026-09-20T08:42:40Z",
    }
    item.update(over)
    return item


@pytest.fixture
def _use_test_session(monkeypatch):
    from conftest import TEST_SESSION

    monkeypatch.setattr(gci, "_session_factory", TEST_SESSION, raising=False)


@pytest.mark.asyncio
async def test_import_creates_posts_and_media(db, user_id, channel_id, monkeypatch, _use_test_session):
    from app.modules.channels.service import encrypt_token

    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("token")
    await db.commit()

    async def _posts(self, account_id, location_id):
        return [_google_post()]

    async def _media(self, account_id, location_id, **kw):
        return {"mediaItems": [_media_item()]}

    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_local_posts", _posts
    )
    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_media", _media
    )

    summary = await gci.import_channel_content(channel_id)
    assert summary["posts"] == 1
    assert summary["media"] == 1

    posts = (await db.execute(select(LocationPost))).scalars().all()
    assert len(posts) == 1
    p = posts[0]
    assert p.google_post_id == "accounts/a/locations/l/localPosts/p1"
    assert p.status == "published"
    assert p.description == "Welcome to our store"
    assert p.image_urls == ["https://example.com/a.jpg"]
    assert p.cta_type == "LEARN_MORE"

    media = (await db.execute(select(LocationMedia))).scalars().all()
    assert len(media) == 1
    m = media[0]
    assert m.google_post_id == "accounts/a/locations/l/media/m1"
    assert m.status == "published"
    assert m.category == "EXTERIOR"
    assert m.image_url == "https://example.com/photo.jpg"


@pytest.mark.asyncio
async def test_import_is_idempotent(db, user_id, channel_id, monkeypatch, _use_test_session):
    from app.modules.channels.service import encrypt_token

    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("token")
    await db.commit()

    async def _posts(self, account_id, location_id):
        return [_google_post()]

    async def _media(self, account_id, location_id, **kw):
        return {"mediaItems": [_media_item()]}

    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_local_posts", _posts
    )
    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_media", _media
    )

    await gci.import_channel_content(channel_id)
    summary = await gci.import_channel_content(channel_id)

    assert summary["posts"] == 0
    assert summary["media"] == 0
    assert len((await db.execute(select(LocationPost))).scalars().all()) == 1
    assert len((await db.execute(select(LocationMedia))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_import_never_overwrites_a_merchant_draft(
    db, user_id, channel_id, monkeypatch, _use_test_session
):
    from app.modules.channels.service import encrypt_token

    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("token")
    await db.commit()

    db.add(LocationPost(
        id="draft-1", user_id=user_id, listing_id="loc-1",
        business_name="Test", title="My draft", description="Mine",
        post_type="update", status="draft",
        google_post_id="accounts/a/locations/l/localPosts/p1",
    ))
    await db.commit()

    async def _posts(self, account_id, location_id):
        return [_google_post(summary="Google's copy")]

    async def _media(self, account_id, location_id, **kw):
        return {"mediaItems": []}

    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_local_posts", _posts
    )
    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_media", _media
    )

    await gci.import_channel_content(channel_id)

    draft = await db.get(LocationPost, "draft-1")
    assert draft.status == "draft"
    assert draft.description == "Mine"


@pytest.mark.asyncio
async def test_import_failure_never_raises(db, user_id, channel_id, monkeypatch, _use_test_session):
    from app.modules.channels.service import encrypt_token

    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("token")
    await db.commit()

    async def _boom(self, account_id, location_id):
        raise RuntimeError("Google exploded")

    monkeypatch.setattr(
        "app.modules.channels.google_reviews.GoogleReviewsClient.list_local_posts", _boom
    )

    summary = await gci.import_channel_content(channel_id)
    assert summary["posts"] == 0
    assert "note" in summary
