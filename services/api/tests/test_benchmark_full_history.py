"""Bounded full-history benchmark review mode."""
from datetime import datetime, timezone

import pytest

from app.modules.benchmark import boq, provider, scraper, service, theme_jobs, theme_service
from app.modules.benchmark.models import BenchmarkPlace

TENANT = "11111111-1111-1111-1111-111111111111"
FTID = "0x3e2eff0029e37d6d:0xf18199ab22d80c09"
MAPS_URL = (
    "https://www.google.com/maps/place/X/data=!4m6!3m5"
    f"!1s{FTID}!8m2!3d24.8!4d46.6"
)


async def test_config_has_bounded_full_history_fields(db):
    config = await service.get_config(db)
    assert config.review_history_mode == "recent"
    assert config.max_reviews_per_place == 2000
    assert config.full_history_batch == 1


async def test_admin_can_set_bounded_full_history(db):
    config = await service.update_config(
        db, review_history_mode="full", max_reviews_per_place=3000,
        full_history_batch=2,
    )
    assert config.review_history_mode == "full"
    assert config.max_reviews_per_place == 3000
    assert config.full_history_batch == 2
    with pytest.raises(service.BenchError):
        await service.update_config(db, review_history_mode="unlimited")


def test_full_history_pages_can_exceed_recent_cap():
    assert boq._pages_for(250) <= boq.MAX_PAGES
    assert boq._pages_for(2000, full_history=True) > boq.MAX_PAGES
    assert boq._pages_for(50_000, full_history=True) <= boq.MAX_PAGES_FULL


async def test_provider_passes_full_history_to_boq(monkeypatch):
    monkeypatch.setattr(provider.places, "configured", lambda: False)
    called = {}

    async def boq_get(place_id, **kwargs):
        called.update(kwargs)
        return {"place_id": place_id, "reviews": [], "name": "X"}

    monkeypatch.setattr(boq, "get_place", boq_get)

    await provider.get_details(
        "google_places", "p1", reviews_limit=2000, maps_url=MAPS_URL,
        full_history=True,
    )

    assert called["full_history"] is True
    assert called["reviews_limit"] == 2000
    assert called["days"] is None


async def test_scraper_full_history_batches_one_place(db, monkeypatch):
    config = await service.get_config(db)
    config.review_history_mode = "full"
    await db.commit()
    for index in range(3):
        db.add(BenchmarkPlace(
            id=f"pk-{index}", tenant_id=TENANT, place_id=f"p-{index}",
            label=f"P{index}", maps_url=MAPS_URL,
        ))
    await db.commit()
    called = []

    async def fake_get_details(source, place_id, **kwargs):
        called.append((place_id, kwargs))
        return {"place_id": place_id, "name": "X", "reviews": []}

    monkeypatch.setattr(provider, "get_details", fake_get_details)

    result = await scraper.refresh_due_places()

    assert result["scraped"] == 1
    assert len(called) == 1
    assert called[0][1]["full_history"] is True
    assert called[0][1]["reviews_limit"] == 2000


async def test_full_history_sample_keeps_more_than_recent_cap(db, user_id):
    from app.modules.analytics.models import ReviewInsight
    from app.modules.channels.models import Channel

    channel = Channel(
        id="full-channel", user_id=user_id, platform="google_reviews",
        platform_user_id="g-full", status="active",
    )
    db.add(channel)
    config = await service.get_config(db)
    config.review_history_mode = "full"
    await db.commit()
    for index in range(60):
        published = datetime.now(timezone.utc).replace(microsecond=0)
        db.add(ReviewInsight(
            id=f"full-review-{index}", user_id=user_id, channel_id=channel.id,
            review_id=f"full-{index}", review_text=f"Great service {index}",
            rating=5, sentiment="positive", review_updated_at=published,
        ))
    await db.commit()

    sample = await theme_service.build_subject_sample(
        db, user_id, f"own:{channel.id}"
    )

    assert sample is not None
    assert len(sample["reviews"]) == 60


async def test_theme_job_uses_local_extraction_above_llm_cap(db, user_id, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("LLM must not see a full-history sample")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", forbidden)
    monkeypatch.setattr(theme_jobs, "complete", forbidden)

    reviews = theme_service.normalize_reviews([
        {"review_id": f"r-{i}", "text": "Great service", "rating": 5}
        for i in range(60)
    ], limit=theme_service.MAX_SAMPLE_REVIEWS_FULL)
    themes = theme_service.extract_local_themes(reviews)

    assert themes
    assert themes[0]["sample_size"] == 60
