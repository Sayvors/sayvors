"""External benchmark peer set: dormant without a key, medians when seeded."""
from datetime import datetime, timezone

import pytest

from app.modules.analytics.competitors import (
    get_external_peer_set,
    places_configured,
    refresh_external_peers,
)
from app.modules.analytics.models import CompetitorSnapshot


@pytest.mark.asyncio
async def test_external_peers_dormant_without_key(db, user_id, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "")
    assert places_configured() is False
    out = await get_external_peer_set(db, user_id)
    assert out["configured"] is False
    assert out["available"] is False
    refreshed = await refresh_external_peers(db, user_id, name="X", address="Riyadh", category="Cafe")
    assert refreshed["configured"] is False
    assert refreshed["inserted"] == 0


@pytest.mark.asyncio
async def test_external_peers_medians_when_seeded(db, user_id, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "test-key")
    now = datetime.now(timezone.utc)
    for i, (rating, reviews) in enumerate(((4.8, 300), (4.5, 180), (4.1, 90))):
        db.add(CompetitorSnapshot(
            id=f"snap-{i}", user_id=user_id, place_id=f"place-{i}",
            name=f"Competitor {i}", rating=rating, review_count=reviews,
            source="google_places", query_radius_m=5000, query_category="Cafe",
            fetched_at=now,
        ))
    await db.commit()

    out = await get_external_peer_set(db, user_id)
    assert out["configured"] is True
    assert out["available"] is True
    assert out["count"] == 3
    assert out["median_rating"] == 4.5
    assert out["median_reviews"] == 180
    assert out["source"] == "google_places"
    assert out["radius_m"] == 5000
