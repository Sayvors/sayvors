"""Location media scheduling + auto-publish (Google push is monkeypatched)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.localith.models import LocalithConnection
from app.modules.media import service as media


async def _connection(db, user_id):
    db.add(LocalithConnection(
        id="conn-media-1", user_id=user_id, listing_id="loc-1",
        listing_name="Test Place", listing_google_id="g1",
    ))
    await db.commit()


def _photo(**over):
    data = {
        "listing_id": "loc-1",
        "image_url": "https://example.com/shop.jpg",
        "type": "PHOTO", "category": "EXTERIOR", "caption": "Fresh look",
        "action": "draft", "scheduled_on": None,
    }
    data.update(over)
    return data


def _future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_create_draft_and_list(db, user_id):
    res = await media.create_media(db, user_id, _photo())
    assert res["media"]["status"] == "draft"
    assert res["google_published"] is False
    rows = await media.list_media(db, user_id, "loc-1")
    assert len(rows) == 1
    assert rows[0]["category"] == "EXTERIOR"


@pytest.mark.asyncio
async def test_create_rejects_non_url_and_bad_schedule(db, user_id):
    with pytest.raises(ValueError):
        await media.create_media(db, user_id, _photo(image_url="local-file.jpg"))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        await media.create_media(db, user_id, _photo(action="schedule", scheduled_on=past))


@pytest.mark.asyncio
async def test_publish_now_posts_photo_inside_google_post(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append((listing_id, kw))
        return {"id": "mpub-1"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await media.create_media(db, user_id, _photo())
    res = await media.publish_media(db, user_id, created["media"]["id"])
    assert res["google_published"] is True
    assert res["media"]["status"] == "published"
    assert res["media"]["google_post_id"] == "mpub-1"
    assert calls[0][0] == "loc-1"
    assert calls[0][1]["image_urls"] == ["https://example.com/shop.jpg"]


@pytest.mark.asyncio
async def test_video_publish_refused(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _boom(*a, **k):
        raise AssertionError("must not reach Google")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _boom
    )
    created = await media.create_media(db, user_id, _photo(type="VIDEO"))
    with pytest.raises(ValueError, match="Video"):
        await media.publish_media(db, user_id, created["media"]["id"])


@pytest.mark.asyncio
async def test_retry_then_park(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await media.create_media(db, user_id, _photo())
    pid = created["media"]["id"]
    await media.update_media(db, user_id, pid, {"status": "scheduled", "scheduled_on": past})
    with pytest.raises(RuntimeError):
        await media.publish_media(db, user_id, pid)
    totals = await media.publish_due(db)
    assert totals["checked"] == 0  # backoff running: skipped silently
    for _ in range(media.MAX_PUBLISH_ATTEMPTS):
        try:
            await media.publish_media(db, user_id, pid)
        except RuntimeError:
            pass
    from sqlalchemy import select as _select
    from app.modules.media.models import LocationMedia
    row = (await db.execute(
        _select(LocationMedia).where(LocationMedia.id == pid)
    )).scalar_one()
    assert row.status == "failed"
    assert row.next_retry_at is None


@pytest.mark.asyncio
async def test_publish_due_only_publishes_due(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(listing_id)
        return {"id": "mpub-x"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    due = await media.create_media(db, user_id, _photo())
    later = await media.create_media(db, user_id, _photo())
    await media.update_media(db, user_id, due["media"]["id"],
                             {"status": "scheduled", "scheduled_on": past})
    await media.update_media(db, user_id, later["media"]["id"],
                             {"status": "scheduled", "scheduled_on": future})
    totals = await media.publish_due(db)
    assert totals["checked"] == 1
    assert totals["published"] == 1
    assert calls == ["loc-1"]


@pytest.mark.asyncio
async def test_delete_and_update_flags(db, user_id):
    created = await media.create_media(db, user_id, _photo())
    pid = created["media"]["id"]
    out = await media.update_media(db, user_id, pid, {"category": "INTERIOR", "is_cover": True})
    assert out["media"]["category"] == "INTERIOR"
    assert out["media"]["is_cover"] is True
    # delete_at set + cancel (exclude_unset semantics at service level).
    out = await media.update_media(db, user_id, pid, {"delete_at": _future()})
    assert out["media"]["delete_at"]
    out = await media.update_media(db, user_id, pid, {"delete_at": None})
    assert out["media"]["delete_at"] is None
    await media.delete_media(db, user_id, pid)
    assert await media.list_media(db, user_id, "loc-1") == []


@pytest.mark.asyncio
async def test_gallery_method_blocked_until_native_google(db, user_id):
    """Gallery/profile publishing is stored intent, never executed —
    Localith offers no gallery upload."""
    with pytest.raises(ValueError, match="native Google"):
        await media.create_media(
            db, user_id,
            {**_photo(), "publish_method": "gallery", "action": "schedule",
             "scheduled_on": _future()},
        )
    created = await media.create_media(
        db, user_id, {**_photo(), "publish_method": "gallery"}
    )
    assert created["media"]["publish_method"] == "gallery"
    with pytest.raises(ValueError, match="native Google"):
        await media.publish_media(db, user_id, created["media"]["id"])


@pytest.mark.asyncio
async def test_delete_due(db, user_id):
    from app.modules.media.models import LocationMedia
    now = datetime.now(timezone.utc)
    db.add(LocationMedia(id="m-due", user_id=user_id, listing_id="loc-1",
                         image_url="https://example.com/a.jpg",
                         delete_at=now - timedelta(minutes=1)))
    db.add(LocationMedia(id="m-keep", user_id=user_id, listing_id="loc-1",
                         image_url="https://example.com/b.jpg",
                         delete_at=now + timedelta(days=1)))
    await db.commit()
    totals = await media.delete_due(db)
    assert totals == {"checked": 1, "deleted": 1}
    remaining = await media.list_media(db, user_id, "loc-1")
    assert [r["id"] for r in remaining] == ["m-keep"]


@pytest.mark.asyncio
async def test_upload_from_computer_returns_public_url(monkeypatch, tmp_path, db, user_id, client):
    """Computer → server → public URL → usable as a media row immediately."""
    from pathlib import Path as _Path

    from app.config import settings

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/media/upload",
        files={"file": ("shop.jpg", b"\xff\xd8fake-bytes", "image/jpeg")},
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["image_url"].startswith("http")
    assert body["image_url"].endswith(".jpg")
    assert body["type"] == "PHOTO"
    assert len(list(_Path(tmp_path).rglob("*.jpg"))) == 1
    # The returned URL flows straight into create (http check passes).
    res = await media.create_media(db, user_id, _photo_for_upload(body["image_url"]))
    assert res["media"]["status"] == "draft"


@pytest.mark.asyncio
async def test_upload_rejects_bad_files(monkeypatch, tmp_path, client):
    from app.config import settings

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/media/upload",
        files={"file": ("evil.exe", b"xx", "application/octet-stream")},
        headers={"host": "localhost"},
    )
    assert r.status_code == 400
    monkeypatch.setattr(settings, "MEDIA_MAX_MB", 1)
    r = client.post(
        "/api/v1/media/upload",
        files={"file": ("big.jpg", b"y" * (2 * 1024 * 1024), "image/jpeg")},
        headers={"host": "localhost"},
    )
    assert r.status_code == 400


def _photo_for_upload(url: str) -> dict:
    return {
        "listing_id": "loc-1", "image_url": url,
        "type": "PHOTO", "category": "EXTERIOR", "caption": "",
        "action": "draft", "scheduled_on": None,
    }
