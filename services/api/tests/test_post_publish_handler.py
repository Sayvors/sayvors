"""The post.publish job hands the composer's choices to the Google publisher.

The button was once dropped here without any error: the feed showed it, the
job stored it, and Google never received it. This pins the hand-off.
"""

from types import SimpleNamespace

import pytest

from app.modules.jobs.handlers import post_publish


@pytest.mark.asyncio
async def test_the_call_to_action_reaches_the_google_publisher(monkeypatch):
    captured: dict = {}
    channel = SimpleNamespace(
        user_id="tenant-1",
        platform="google_reviews",
        platform_user_id="117",
        listing_key="loc-1",
        metadata_json='{"location_id": "loc-1"}',
        access_token="enc",
        refresh_token="enc",
        token_expires_at=None,
    )

    async def fake_resolve(db, tenant_id, platform, external_asset_id):
        return channel

    class FakePublisher:
        def __init__(self, token, refresh=None):
            pass

        def set_token_persister(self, persister):
            pass

        def set_known_expiry(self, expires_at):
            pass

        async def publish_post(self, **kwargs):
            captured.update(kwargs)
            return {"id": "accounts/117/locations/loc-1/localPosts/9", "state": "LIVE"}

    async def fake_complete(db, job, result):
        captured["result"] = result

    monkeypatch.setattr(post_publish, "_resolve_channel", fake_resolve)
    monkeypatch.setattr(post_publish, "GoogleBusinessPublisher", FakePublisher)
    monkeypatch.setattr(post_publish, "decrypt_token", lambda value: "plain")
    monkeypatch.setattr(post_publish, "complete_job", fake_complete)

    job = SimpleNamespace(
        id="job-1",
        tenant_id="tenant-1",
        payload={
            "platform": "google_reviews",
            "external_asset_id": "loc-1",
            "method": "update",
            "caption": "Hello",
            "description": "",
            "media_url": None,
            "media_type": None,
            "cta_type": "shop",
            "cta_url": "https://shop.example.com",
            "scheduled_at": None,
            "delete_at": None,
        },
    )
    await post_publish.handle_post_publish(job, db=None)

    assert captured["cta_type"] == "shop"
    assert captured["cta_url"] == "https://shop.example.com"
    assert captured["result"]["state"] == "LIVE"
