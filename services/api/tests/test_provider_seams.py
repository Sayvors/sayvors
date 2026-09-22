"""Provider seams: Localith today, Google native when GBP API lands.

Defaults keep every existing behavior (Localith). Flipping a flag to
"google" before its native client exists fails loudly — never silently.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core import providers


def test_defaults_are_localith(monkeypatch):
    monkeypatch.delenv("LOCATIONS_WRITE_PROVIDER", raising=False)
    monkeypatch.delenv("MEDIA_PUBLISH_PROVIDER", raising=False)
    assert providers.locations_write_provider() == "localith"
    assert providers.media_publish_provider() == "localith"


def test_invalid_value_rejected(monkeypatch):
    monkeypatch.setenv("LOCATIONS_WRITE_PROVIDER", "acme")
    with pytest.raises(ValueError, match="LOCATIONS_WRITE_PROVIDER"):
        providers.locations_write_provider()
    monkeypatch.setenv("MEDIA_PUBLISH_PROVIDER", "ACME")
    with pytest.raises(ValueError, match="MEDIA_PUBLISH_PROVIDER"):
        providers.media_publish_provider()


@pytest.mark.asyncio
async def test_locations_google_flag_fails_loudly(monkeypatch, db, user_id):
    """Premature flip: NotImplementedError, never a wrapped RuntimeError."""
    from app.modules.locations import service as locations
    from app.modules.localith.models import LocalithConnection

    db.add(LocalithConnection(
        id="conn-seam-1", user_id=user_id, listing_id="loc-1",
        listing_name="Seam Place",
    ))
    await db.commit()
    monkeypatch.setenv("LOCATIONS_WRITE_PROVIDER", "google")
    with pytest.raises(NotImplementedError, match="GBP API access"):
        await locations.update_profile(
            db, user_id, "loc-1", description="New blurb",
            categories=None, hours=None, service_area=None, attributes=None,
        )


@pytest.mark.asyncio
async def test_locations_default_still_pushes_localith(monkeypatch, db, user_id):
    from integrations.channels import embedsocial

    from app.modules.locations import service as locations
    from app.modules.localith.models import LocalithConnection

    db.add(LocalithConnection(
        id="conn-seam-2", user_id=user_id, listing_id="loc-1",
        listing_name="Seam Place",
    ))
    await db.commit()
    calls = []

    def _fake_update(listing_id, payload):
        calls.append((listing_id, payload))
        return {}

    monkeypatch.setattr(embedsocial, "update_listing", _fake_update)
    monkeypatch.delenv("LOCATIONS_WRITE_PROVIDER", raising=False)
    out = await locations.update_profile(
        db, user_id, "loc-1", description="New blurb",
        categories=None, hours=None, service_area=None, attributes=None,
    )
    assert out["description"] == "New blurb"
    assert calls == [("loc-1", {"description": "New blurb"})]


@pytest.mark.asyncio
async def test_media_google_flag_fails_loudly(monkeypatch, db, user_id):
    """Premature flip: NotImplementedError before any failure bookkeeping
    (no failed row, no notification, no retry scheduled)."""
    from sqlalchemy import select as _select

    from app.modules.localith.models import LocalithConnection
    from app.modules.media import service as media
    from app.modules.media.models import LocationMedia

    db.add(LocalithConnection(
        id="conn-seam-3", user_id=user_id, listing_id="loc-1",
        listing_name="Seam Place",
    ))
    db.add(LocationMedia(
        id="m-seam-1", user_id=user_id, listing_id="loc-1",
        category="EXTERIOR", type="PHOTO",
        image_url="https://example.com/shop.jpg", status="draft",
    ))
    await db.commit()
    monkeypatch.setenv("MEDIA_PUBLISH_PROVIDER", "google")
    with pytest.raises(NotImplementedError, match="GBP API access"):
        await media.publish_media(db, user_id, "m-seam-1")
    row = (await db.execute(
        _select(LocationMedia).where(LocationMedia.id == "m-seam-1")
    )).scalar_one()
    assert row.status == "draft"  # untouched: no failure recorded


@pytest.mark.asyncio
async def test_media_default_still_publishes_localith(monkeypatch, db, user_id):
    from app.modules.localith.models import LocalithConnection
    from app.modules.media import service as media
    from app.modules.media.models import LocationMedia

    db.add(LocalithConnection(
        id="conn-seam-4", user_id=user_id, listing_id="loc-1",
        listing_name="Seam Place",
    ))
    db.add(LocationMedia(
        id="m-seam-2", user_id=user_id, listing_id="loc-1",
        category="EXTERIOR", type="PHOTO",
        image_url="https://example.com/shop.jpg", status="draft",
    ))
    await db.commit()
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append((listing_id, kw))
        return {"id": "mpub-seam"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    monkeypatch.delenv("MEDIA_PUBLISH_PROVIDER", raising=False)
    res = await media.publish_media(db, user_id, "m-seam-2")
    assert res["media"]["status"] == "published"
    assert calls[0][0] == "loc-1"
