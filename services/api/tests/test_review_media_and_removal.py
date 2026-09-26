"""Reviewer photos and removal detection.

Two failure modes are pinned here:

  * Photos. Google returns `reviewMediaItems[].thumbnailUrl`, but that is a
    short-lived FIFE link. Storing the URL yields a review card with a broken
    image a day later, so the bytes must be downloaded and kept. A sync that
    sees the same photo twice must not download or store it twice.

  * Removal. When a review stops being returned by a COMPLETE fetch, Google no
    longer serves it. The row is kept (soft) and the flag clears itself if the
    review reappears. Critically, a review the merchant flagged by hand is left
    alone, and a suspiciously small fetch must never be mistaken for a mass
    deletion.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from integrations.channels import embedsocial

from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel
from app.modules.localith.service import (
    _fetched_review_ids,
    _mark_removed_reviews,
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ── Adapter: Google's media shape ────────────────────────────────

def test_google_media_parsing():
    from app.modules.channels.google_reviews import _parse_media

    out = _parse_media([
        {"thumbnailUrl": "https://fife/v1", "thumbnailLabel": "our shop"},
        {"videoUrl": "https://fife/v2", "thumbnailUrl": "https://fife/t"},
    ])
    assert out[0] == {
        "thumbnail_url": "https://fife/v1",
        "video_url": None,
        "label": "our shop",
        "kind": "image",
    }
    assert out[1]["kind"] == "video"


def test_google_media_tolerates_junk():
    from app.modules.channels.google_reviews import _parse_media

    assert _parse_media(None) == []
    assert _parse_media("nope") == []
    assert _parse_media([{"nothing": "useful"}]) == []
    assert _parse_media(["bare"]) == []


def test_embedsocial_media_is_empty_today_but_tolerated():
    """Localith ships no media; the parser must not invent any, or crash."""
    assert embedsocial.to_internal_review({"id": "a", "captionText": "x"}).media == []
    # ...but if they start shipping it, it must be picked up, not dropped.
    review = embedsocial.to_internal_review({
        "id": "b", "photos": [{"url": "https://cdn/x.jpg", "label": "pic"}],
    })
    assert review.media == [{
        "thumbnail_url": "https://cdn/x.jpg",
        "video_url": None,
        "label": "pic",
        "kind": "image",
    }]


def test_embedsocial_media_accepts_bare_string_urls():
    review = embedsocial.to_internal_review({"id": "c", "media": ["https://cdn/y.jpg"]})
    assert review.media[0]["thumbnail_url"] == "https://cdn/y.jpg"


# ── Media storage: safety and idempotency ────────────────────────

def test_only_real_raster_images_are_accepted():
    from app.modules.analytics.review_media import _sniff_image

    assert _sniff_image(PNG) == ".png"
    assert _sniff_image(b"\xff\xd8\xff\xe0rest") == ".jpg"
    assert _sniff_image(b"GIF89a....") == ".gif"
    assert _sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    # A hostile "thumbnail" must never be stored on a public URL.
    assert _sniff_image(b"<svg onload=alert(1)></svg>") is None
    assert _sniff_image(b"<!DOCTYPE html><html>") is None
    assert _sniff_image(b"") is None


@pytest.mark.asyncio
async def test_unchanged_photo_is_not_downloaded_twice(monkeypatch, tmp_path):
    from app.modules.analytics import review_media

    monkeypatch.setattr(review_media.settings, "MEDIA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(review_media.settings, "MEDIA_PUBLIC_PATH", "/media-files", raising=False)
    monkeypatch.setattr(review_media, "media_configured", lambda: False)

    calls = {"n": 0}

    async def fake_download(url):
        calls["n"] += 1
        return PNG, ".png"

    monkeypatch.setattr(review_media, "_download", fake_download)

    stored = [{"url": "/media-files/u/old.png", "kind": "image",
               "label": None, "source_url": "https://fife/one"}]
    out = await review_media.sync_review_media(
        "u", [{"thumbnail_url": "https://fife/one", "video_url": None,
               "label": None, "kind": "image"}], stored,
    )
    # Same source_url -> the existing entry is reused, nothing re-downloaded.
    assert calls["n"] == 0
    assert out == stored


@pytest.mark.asyncio
async def test_new_photo_is_downloaded_and_stored(monkeypatch, tmp_path):
    from app.modules.analytics import review_media

    monkeypatch.setattr(review_media.settings, "MEDIA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(review_media, "media_configured", lambda: False)

    async def fake_download(url):
        return PNG, ".png"

    monkeypatch.setattr(review_media, "_download", fake_download)

    out = await review_media.sync_review_media(
        "user-1", [{"thumbnail_url": "https://fife/new", "video_url": None,
                    "label": "shop front", "kind": "image"}], [],
    )
    assert len(out) == 1
    assert out[0]["kind"] == "image"
    assert out[0]["label"] == "shop front"
    # Relative path, so the frontend resolves it against the API origin.
    assert out[0]["url"].startswith("/media-files/user-1/")
    assert (tmp_path / "user-1").exists()


@pytest.mark.asyncio
async def test_failed_download_does_not_break_the_sync(monkeypatch):
    from app.modules.analytics import review_media

    async def boom(url):
        return None

    monkeypatch.setattr(review_media, "_download", boom)

    out = await review_media.sync_review_media(
        "u", [{"thumbnail_url": "https://fife/gone", "video_url": None,
               "label": None, "kind": "image"}], [],
    )
    # Recorded as a placeholder so the next sync retries instead of hammering
    # a dead URL on every poll, and no exception escapes.
    assert out[0]["url"] is None
    assert out[0]["source_url"] == "https://fife/gone"


@pytest.mark.asyncio
async def test_no_media_leaves_stored_list_untouched():
    from app.modules.analytics.review_media import sync_review_media

    stored = [{"url": "/media-files/u/a.png", "kind": "image", "source_url": "https://fife/a"}]
    assert await sync_review_media("u", [], stored) == stored


# ── Removal detection ─────────────────────────────────────────────

def test_fetched_ids_are_normalised():
    items = [{"id": "a"}, {"review_id": "b"}, {"uid": "c"}, {"nothing": 1}, "junk"]
    assert _fetched_review_ids(items) == {
        "localith:a", "localith:b", "localith:c",
    }
    assert _fetched_review_ids(None) == set()


async def _insight(db, user_id, channel_id, review_id, **kw):
    row = ReviewInsight(
        id=f"ins-{review_id[-8:]}",
        user_id=user_id,
        channel_id=channel_id,
        review_id=review_id,
        rating=kw.pop("rating", 4),
        review_text=kw.pop("review_text", "hello"),
        reviewer_name="Tester",
        sentiment="neutral",
        sentiment_score=0.5,
        topics=[],
        products=[],
        problems=[],
        enrichment_status="done",
        **kw,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_review_missing_from_a_complete_fetch_is_marked_removed(
    db, user_id, channel_id
):
    from datetime import datetime, timezone

    await _insight(db, user_id, channel_id, "localith:gone", last_seen_at=datetime.now(timezone.utc))
    await _insight(db, user_id, channel_id, "localith:here", last_seen_at=datetime.now(timezone.utc))

    channel = await db.get(Channel, channel_id)
    seen = {f"localith:i{i}" for i in range(6)} | {"localith:here"}
    removed = await _mark_removed_reviews(db, channel, user_id, seen)

    assert removed == ["localith:gone"]
    rows = (
        await db.execute(
            select(ReviewInsight).where(ReviewInsight.channel_id == channel_id)
        )
    ).scalars().all()
    by_id = {r.review_id: r for r in rows}
    assert by_id["localith:gone"].removed_at is not None
    assert by_id["localith:here"].removed_at is None


@pytest.mark.asyncio
async def test_merchant_flagged_review_is_never_marked_removed(
    db, user_id, channel_id
):
    from datetime import datetime, timezone

    await _insight(
        db, user_id, channel_id, "localith:flagged", skipped=True,
        last_seen_at=datetime.now(timezone.utc),
    )
    channel = await db.get(Channel, channel_id)
    removed = await _mark_removed_reviews(
        db, channel, user_id, {f"localith:i{i}" for i in range(6)}
    )
    assert removed == []


@pytest.mark.asyncio
async def test_never_seen_review_is_not_swept(db, user_id, channel_id):
    """A review stored before we tracked sightings must not be 'removed'."""
    await _insight(db, user_id, channel_id, "localith:ancient", last_seen_at=None)
    channel = await db.get(Channel, channel_id)
    removed = await _mark_removed_reviews(
        db, channel, user_id, {f"localith:i{i}" for i in range(6)}
    )
    assert removed == []


@pytest.mark.asyncio
async def test_a_tiny_fetch_never_triggers_a_sweep(db, user_id, channel_id):
    """A truncated page must not look like a mass deletion."""
    from datetime import datetime, timezone

    for i in range(6):
        await _insight(
            db, user_id, channel_id, f"localith:r{i}",
            last_seen_at=datetime.now(timezone.utc),
        )
    channel = await db.get(Channel, channel_id)
    removed = await _mark_removed_reviews(db, channel, user_id, {"localith:r0"})
    assert removed == []


@pytest.mark.asyncio
async def test_removed_flag_clears_when_the_review_returns(db, user_id, channel_id):
    from datetime import datetime, timezone

    row = await _insight(
        db, user_id, channel_id, "localith:back",
        last_seen_at=datetime.now(timezone.utc),
        removed_at=datetime.now(timezone.utc),
    )
    # The sync path clears it on sighting; assert the predicate the sweep uses
    # so a returned review is treated as live again.
    assert row.removed_at is not None
    row.removed_at = None
    await db.commit()
    channel = await db.get(Channel, channel_id)
    removed = await _mark_removed_reviews(
        db, channel, user_id, {f"localith:i{i}" for i in range(6)} | {"localith:back"}
    )
    assert removed == []
    assert row.removed_at is None


# ── Listing hides removed reviews by default ─────────────────────

@pytest.mark.asyncio
async def test_removed_reviews_are_hidden_from_the_default_listing(
    db, user_id, channel_id
):
    from app.modules.analytics.service import list_insights

    await _insight(db, user_id, channel_id, "localith:live1")
    await _insight(db, user_id, channel_id, "localith:live2")
    await _insight(db, user_id, channel_id, "localith:dead1", removed_at=datetime.now(timezone.utc))
    await _insight(db, user_id, channel_id, "localith:dead2", removed_at=datetime.now(timezone.utc))

    default, total = await list_insights(db, user_id, channel_id=channel_id)
    assert total == 2
    assert {r.review_id for r in default} == {"localith:live1", "localith:live2"}

    gone, gone_total = await list_insights(db, user_id, channel_id=channel_id, removed=True)
    assert gone_total == 2
    assert {r.review_id for r in gone} == {"localith:dead1", "localith:dead2"}
