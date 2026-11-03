"""External benchmark peer set: dormant without a key, medians when seeded."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.analytics.competitors import (
    get_external_peer_set,
    places_configured,
    refresh_external_peers,
)
from app.modules.analytics.models import CompetitorSnapshot, CompetitorSnapshotHistory


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


@pytest.mark.asyncio
async def test_external_peers_include_30_day_deltas(db, user_id, monkeypatch):
    from datetime import timedelta

    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "test-key")
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=45)

    for i, (old_rating, old_reviews, new_rating, new_reviews) in enumerate((
        (4.0, 100, 4.2, 110),
        (4.2, 200, 4.4, 205),
        (4.4, 300, 4.6, 315),
    )):
        db.add(CompetitorSnapshot(
            id=f"snap-{i}", user_id=user_id, place_id=f"place-{i}",
            name=f"Competitor {i}", rating=new_rating, review_count=new_reviews,
            source="google_places", query_radius_m=5000, query_category="Cafe",
            fetched_at=now,
        ))
        db.add(CompetitorSnapshotHistory(
            id=f"history-{i}", user_id=user_id, place_id=f"place-{i}",
            name=f"Competitor {i}", rating=old_rating, review_count=old_reviews,
            source="google_places", query_radius_m=5000, query_category="Cafe",
            fetched_at=old,
        ))
    await db.commit()

    out = await get_external_peer_set(db, user_id)

    assert out["delta_window_days"] == 30
    assert out["median_rating_delta"] == 0.2
    assert out["median_reviews_delta"] == 10
    peer = next(p for p in out["peers"] if p["place_id"] == "place-0")
    assert peer["rating_delta"] == 0.2
    assert peer["reviews_delta"] == 10
    assert peer["baseline_days"] == 45


@pytest.mark.asyncio
async def test_refresh_preserves_a_history_cycle(db, user_id, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "test-key")

    async def _fake_search(_query, _max_results):
        return [
            {"place_id": "place-1", "name": "A", "category": "Cafe", "address": "Riyadh", "rating": 4.4, "review_count": 120},
            {"place_id": "place-2", "name": "B", "category": "Cafe", "address": "Riyadh", "rating": 4.2, "review_count": 80},
            {"place_id": "place-3", "name": "C", "category": "Cafe", "address": "Riyadh", "rating": 4.0, "review_count": 40},
        ]

    monkeypatch.setattr("app.modules.analytics.competitors._search_text", _fake_search)
    await refresh_external_peers(db, user_id, name="Me", address="Riyadh", category="Cafe")

    rows = (await db.execute(
        select(CompetitorSnapshotHistory).where(
            CompetitorSnapshotHistory.user_id == user_id
        )
    )).scalars().all()
    assert len(rows) == 3
