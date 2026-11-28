"""Scheduled benchmark collector: free-provider fallback and safe skips."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.benchmark import boq, places, provider, scraper, service
from app.modules.benchmark.models import BenchmarkPlace, BenchmarkSnapshot

TENANT = "11111111-1111-1111-1111-111111111111"
FTID = "0x3e2eff0029e37d6d:0xf18199ab22d80c09"
MAPS_URL = f"https://www.google.com/maps/place/X/data=!4m6!3m5!1s{FTID}!8m2!3d24.8!4d46.6"


@pytest.fixture(autouse=True)
def _places_unavailable_without_network(monkeypatch):
    """The old path must fail immediately; RED should not wait on Google."""

    async def unavailable(place_id, **kwargs):
        raise places.PlacesError("Places has no key", 503)

    monkeypatch.setattr(places, "get_place", unavailable)


async def _row(db, place_id: str, maps_url: str | None = MAPS_URL):
    row = BenchmarkPlace(
        id=f"pk-{place_id}", tenant_id=TENANT, place_id=place_id, label=place_id,
        rating=4.1, review_count=100, maps_url=maps_url,
    )
    db.add(row)
    await db.commit()
    return row


async def test_worker_uses_provider_strategy_for_official_source(db, monkeypatch):
    config = await service.get_config(db)
    config.source = "google_places"
    await db.commit()
    await _row(db, "official-1")
    called = {}

    async def fake_get_details(source, place_id, **kwargs):
        called.update({"source": source, "place_id": place_id, **kwargs})
        return {
            "place_id": place_id, "name": "Official Cafe", "rating": 4.4,
            "review_count": 120, "reviews": [{"rating": 5}] * 500,
        }

    monkeypatch.setattr(provider, "get_details", fake_get_details)

    result = await scraper.refresh_due_places()

    assert result["scraped"] == 1
    assert called["source"] == "google_places"
    assert called["reviews_limit"] == 250
    assert called["maps_url"] == MAPS_URL


async def test_unconfigured_provider_falls_back_to_the_free_provider(db, monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: False)
    row = await _row(db, "free-1")
    called = {}

    async def fake_get_place(place_id, **kwargs):
        called.update(kwargs)
        return {
            "place_id": place_id, "name": "Free Cafe", "rating": 4.5,
            "review_count": 120, "reviews": [{"review_id": "r1", "rating": 5}],
            "thumbnail": "https://lh3.googleusercontent.com/cover",
        }

    monkeypatch.setattr(boq, "get_place", fake_get_place)

    result = await scraper.refresh_due_places()

    assert result["scraped"] == 1
    assert called["maps_url"] == MAPS_URL
    assert called["reviews_limit"] == 250
    assert called["days"] is None
    await db.refresh(row)
    assert row.rating == 4.5
    assert row.review_count == 120
    assert row.thumbnail == "https://lh3.googleusercontent.com/cover"
    assert row.reviews == [{"review_id": "r1", "rating": 5}]
    assert row.last_scrape_error is None
    assert row.fetched_at is not None
    snapshot = (
        await db.execute(
            select(BenchmarkSnapshot).where(
                BenchmarkSnapshot.place_id == row.id
            )
        )
    ).scalar_one()
    assert snapshot.rating == 4.5
    assert snapshot.review_count == 120


async def test_free_provider_skips_legacy_rows_without_a_feature_id(db, monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: False)
    row = await _row(db, "legacy-no-url", maps_url=None)

    async def fail(*args, **kwargs):
        raise AssertionError("free provider called without a feature id")

    monkeypatch.setattr(boq, "get_place", fail)

    result = await scraper.refresh_due_places()

    assert result["scraped"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 1
    await db.refresh(row)
    assert row.last_scrape_error is None
    assert row.fetched_at is None


async def test_legacy_gosom_setting_routes_to_the_free_provider(db, monkeypatch):
    config = await service.get_config(db)
    config.source = "gosom"  # old rows survive the migration in a running DB
    await db.commit()
    await _row(db, "legacy-setting")

    async def fake(place_id, **kwargs):
        return {"place_id": place_id, "name": "Rival", "rating": 4.2, "reviews": []}

    monkeypatch.setattr(boq, "get_place", fake)
    result = await scraper.refresh_due_places()

    assert result["scraped"] == 1


async def test_due_rows_with_a_recent_snapshot_are_not_refreshed(db, monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: False)
    row = await _row(db, "fresh")
    now = datetime.now(timezone.utc)
    db.add(BenchmarkSnapshot(
        place_id=row.id, tenant_id=TENANT, rating=4.1, review_count=100,
        fetched_at=now - timedelta(minutes=1),
    ))
    await db.commit()

    result = await scraper.refresh_due_places(now=now)

    assert result["due"] == 0
    assert result["scraped"] == 0


async def test_one_pass_is_capped_at_the_bounded_batch(db, monkeypatch):
    monkeypatch.setattr(places, "configured", lambda: False)
    for index in range(scraper.BATCH_LIMIT + 1):
        await _row(db, f"batch-{index}")
    calls = []

    async def fake(place_id, **kwargs):
        calls.append(place_id)
        return {"place_id": place_id, "name": place_id, "rating": 4.2, "reviews": []}

    monkeypatch.setattr(boq, "get_place", fake)

    result = await scraper.refresh_due_places()

    assert scraper.BATCH_LIMIT == 10
    assert len(calls) == scraper.BATCH_LIMIT
    assert result["scraped"] == scraper.BATCH_LIMIT
    assert result["due"] == scraper.BATCH_LIMIT

    second = await scraper.refresh_due_places()
    assert second["scraped"] == 1


async def test_capacity_warning_when_saved_cap_exceeds_refresh_throughput(db):
    config = await service.get_config(db)
    config.refresh_hours = 1
    config.max_saved_places = 500
    await db.commit()

    warning = scraper.capacity_warning(config)
    assert warning
    assert "120" in warning

    config.max_saved_places = 100
    await db.commit()
    assert scraper.capacity_warning(config) is None
