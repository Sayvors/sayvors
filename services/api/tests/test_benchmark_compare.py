"""Two-sided comparison facts: scoping, normalization and honest empty states."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.modules.analytics.models import ReviewInsight
from app.modules.benchmark import compare
from app.modules.benchmark.models import BenchmarkPlace, BenchmarkSnapshot

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _paid_source_for_places_tests(db, monkeypatch):
    """These tests exercise the paid-provider branches explicitly.

    The product default is now the free provider; tests that want Places must
    say so, while boq/outscraper tests override this in their own body.
    """
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    config = await bench_service.get_config(db)
    config.source = "google_places"
    await db.commit()
    monkeypatch.setattr(places_module, "configured", lambda: True)

TENANT = "tenant-compare"


async def test_parse_subject():
    assert compare.parse_subject("saved:ChIJ123") == ("saved", "ChIJ123")
    assert compare.parse_subject("own:channel-1") == ("own", "channel-1")
    for bad in ("", "saved:", "unknown:abc", "saved", "own:", "places:abc"):
        with pytest.raises(compare.CompareError):
            compare.parse_subject(bad)


async def test_scan_reviews_counts_windows_stars_and_sentiment():
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    old = (now - timedelta(days=40)).isoformat()
    reviews = [
        {"rating": 5, "text": "Great beans", "publish_time": recent},
        {"rating": 1, "text": "Cold coffee", "publish_time": old},
        {"rating": 4, "text": "Lovely roast", "publish_time": recent},
    ]
    scan = compare._scan_reviews(reviews)
    assert scan["windows"]["reviews_last_week"] == 2
    assert scan["windows"]["reviews_last_month"] == 2
    assert scan["windows"]["reviews_last_year"] == 3
    assert scan["stars"][5] == 1 and scan["stars"][1] == 1
    assert scan["positive_pct"] == 66.7
    assert scan["negative_pct"] == 33.3
    assert "text_counts" not in scan


async def test_saved_star_share_uses_sample_when_full_distribution_missing(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="star-sample", label="Sample Cafe",
        rating=4.4, review_count=900,
    )

    async def _fake(place_id, **kwargs):
        return {
            "place_id": place_id, "name": "Sample Cafe", "address": None,
            "rating": 4.4, "review_count": 900, "types": [],
            "reviews": [
                {"rating": 5, "text": "great", "publish_time": "2026-11-24T00:00:00Z"},
                {"rating": 1, "text": "bad", "publish_time": "2026-11-23T00:00:00Z"},
            ],
        }

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(db, TENANT, ["saved:star-sample"]))[0]
    assert result["metrics"]["five_star"] == 1
    assert result["metrics"]["one_star"] == 1
    assert result["metrics"]["star_share_base"] == 2


async def test_saved_star_share_uses_full_distribution_when_available(db):
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="star-full", label="Full Cafe",
        rating=4.4, review_count=900,
    )
    saved.reviews_per_score = {"5": 800, "1": 100}
    await db.commit()

    result = (await compare.compare_subjects(db, TENANT, ["saved:star-full"]))[0]
    assert result["metrics"]["five_star"] == 800
    assert result["metrics"]["one_star"] == 100
    assert result["metrics"]["star_share_base"] == 900
    assert any("full rating distribution" in note for note in result["notes"])
    assert not any("review-text facts" in note for note in result["notes"])


async def test_saved_star_share_ignores_malformed_full_distribution(db):
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="star-malformed", label="Malformed Cafe",
        rating=4.4, review_count=900,
    )
    saved.reviews_per_score = {"5": "not-a-number", "1": 100}
    saved.reviews = [
        {"rating": 5, "text": "great", "publish_time": "2026-11-24T00:00:00Z"},
        {"rating": 1, "text": "bad", "publish_time": "2026-11-23T00:00:00Z"},
    ]
    await db.commit()

    result = (await compare.compare_subjects(db, TENANT, ["saved:star-malformed"]))[0]
    assert result["available"] is True
    assert result["metrics"]["five_star"] == 1
    assert result["metrics"]["one_star"] == 1
    assert result["metrics"]["star_share_base"] == 2


async def test_saved_subject_uses_places_and_flags_hidden_facts(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(db, TENANT, place_id="cmp-1", label="Rival Cafe")

    async def _fake_get_place(place_id, **kwargs):
        assert place_id == "cmp-1"
        now = datetime.now(timezone.utc)
        return {
            "place_id": "cmp-1",
            "name": "Rival Cafe",
            "address": "Riyadh",
            "rating": 4.4,
            "review_count": 900,
            "types": ["cafe", "coffee_shop"],
            "reviews": [
                {"rating": 5, "text": "helpful staff", "publish_time": (now - timedelta(days=1)).isoformat()},
                {"rating": 2, "text": "bad parking", "publish_time": (now - timedelta(days=1)).isoformat()},
            ],
        }

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    result = (await compare.compare_subjects(db, TENANT, ["saved:cmp-1"]))[0]

    assert result["available"] is True
    assert result["name"] == "Rival Cafe"
    assert result["metrics"]["total_reviews"] == 900
    assert result["metrics"]["avg_rating"] == 4.4
    assert result["metrics"]["reviews_last_week"] == 2
    assert result["metrics"]["five_star"] == 1 and result["metrics"]["one_star"] == 0
    assert result["metrics"]["impressions"] is None  # owner-only fact
    assert result["metrics"]["calls"] is None
    assert result["facts"]["services"] == ["Cafe", "Coffee shop"]
    assert "only available to the listing owner" in result["notes"][-1]


async def test_saved_subject_falls_back_to_stored_values_when_live_fails(db, monkeypatch):
    """A Places outage must not blank the column: the bench row still has the
    name and the numbers captured when the business was saved."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(
        db, TENANT, place_id="cmp-down", label="Offline Bakery",
        rating=4.1, review_count=250,
    )

    async def _boom(place_id, **kwargs):
        raise places_module.PlacesError("quota exceeded", status_code=503)

    monkeypatch.setattr(places_module, "get_place", _boom)
    result = (await compare.compare_subjects(db, TENANT, ["saved:cmp-down"]))[0]

    assert result["available"] is True
    assert result["name"] == "Offline Bakery"
    assert result["metrics"]["avg_rating"] == 4.1
    assert result["metrics"]["total_reviews"] == 250
    assert result["metrics"]["five_star"] is None  # no review sample available
    assert any("last known values" in note for note in result["notes"])


async def test_saved_subject_not_on_bench_is_unavailable(db):
    result = (await compare.compare_subjects(db, TENANT, ["saved:not-mine"]))[0]
    assert result["available"] is False
    assert "not on your bench" in result["reason"]


async def test_own_subject_uses_analytics(db, channel_id, user_id):
    result = (await compare.compare_subjects(db, user_id, [f"own:{channel_id}"]))[0]
    assert result["available"] is True
    assert result["data_source"] == "sayvors_analytics"
    assert result["name"] == "Test Burgers"
    assert result["metrics"]["total_reviews"] == 0
    assert result["metrics"]["reviews_last_day"] == 0
    assert result["metrics"]["impressions"] == 0
    assert result["facts"]["branch"] == "Test Burgers"
    assert result["verified"] is False


async def test_own_subject_scoped_to_tenant(db, channel_id, user_id, other_user_id):
    result = (await compare.compare_subjects(db, other_user_id, [f"own:{channel_id}"]))[0]
    assert result["available"] is False
    assert "not connected" in result["reason"]


async def test_two_sides_and_bad_side_do_not_break_each_other(db, channel_id, user_id):
    results = await compare.compare_subjects(
        db, user_id, [f"own:{channel_id}", "garbage"]
    )
    assert len(results) == 2
    assert results[0]["available"] is True
    assert results[1]["available"] is False


async def test_up_to_six_subjects_allowed(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    for i in range(6):
        await bench_service.save_place(db, TENANT, place_id=f"multi-{i}")

    async def _fake_get_place(place_id, **kwargs):
        return {"place_id": place_id, "name": place_id, "address": None,
                "rating": 4.0, "review_count": 10, "types": [], "reviews": []}

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    keys = [f"saved:multi-{i}" for i in range(6)]
    results = await compare.compare_subjects(db, TENANT, keys)
    assert len(results) == 6
    assert all(result["available"] for result in results)
    with pytest.raises(compare.CompareError):
        await compare.compare_subjects(db, TENANT, keys + ["saved:multi-0"])


async def test_compare_endpoint(client, monkeypatch):
    from app.modules.benchmark import places as places_module

    created = client.post(
        "/api/v1/benchmark/places", json={"place_id": "http-1", "label": "HTTP Rival"}
    )
    assert created.status_code == 201, created.text

    async def _fake_get_place(place_id, **kwargs):
        return {
            "place_id": "http-1", "name": "HTTP Rival", "address": None,
            "rating": 4.2, "review_count": 42, "types": [], "reviews": [],
        }

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    res = client.get("/api/v1/benchmark/compare?subjects=saved%3Ahttp-1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["subjects"]) == 1
    assert body["subjects"][0]["name"] == "HTTP Rival"
    assert body["subjects"][0]["metrics"]["total_reviews"] == 42


# ── Period filter: snapshot history + live values ──────────────────────────

async def _fake_details(place_id, **overrides):
    payload = {
        "place_id": place_id, "name": place_id, "address": None,
        "rating": 4.4, "review_count": 900, "types": [], "reviews": [],
    }
    payload.update(overrides)
    return payload


async def test_period_view_serves_fresh_cache_without_calling_places(db, monkeypatch):
    """With data newer than the admin cadence, the period views must not hit
    Places at all — that is the API-cost win."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="cache-1", label="Cached Rival", rating=4.2, review_count=500
    )
    now = datetime.now(timezone.utc)
    await bench_service.store_place_details(
        db, saved, {"name": "Cached Rival", "rating": 4.2, "review_count": 500,
                    "types": ["cafe"], "address": "1 Main St"},
        now=now, append_snapshot=False,
    )
    snapshots_before = (
        await db.execute(
            select(func.count()).select_from(BenchmarkSnapshot)
            .where(BenchmarkSnapshot.place_id == saved.id)
        )
    ).scalar()

    async def _must_not_call(place_id, **kwargs):
        raise AssertionError("Places was called although the cache was fresh")

    monkeypatch.setattr(places_module, "get_place", _must_not_call)
    result = (await compare.compare_subjects(
        db, TENANT, ["saved:cache-1"], days=30
    ))[0]
    assert result["available"] is True
    assert result["metrics"]["total_reviews"] == 500
    assert result["facts"]["services"] == ["Cafe"]
    assert result["facts"]["branch"] == "Cached Rival"
    assert result["address"] == "1 Main St"
    assert any("Google could not be reached" not in note for note in result["notes"])
    snapshots_after = (
        await db.execute(
            select(func.count()).select_from(BenchmarkSnapshot)
            .where(BenchmarkSnapshot.place_id == saved.id)
        )
    ).scalar()
    assert snapshots_after == snapshots_before


async def test_stale_cache_calls_places_and_stores_a_snapshot(db, monkeypatch):
    """A stale cache refreshes live, and the live read doubles as the
    periodic scrape when none has run yet."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="cache-2", label="Stale Rival", rating=4.1, review_count=400
    )
    # Older than the default 24h cadence; `save_place` wrote its snapshot at
    # "now", which counts as a recent snapshot and so is not duplicated.
    await db.execute(
        update(BenchmarkPlace).where(BenchmarkPlace.id == saved.id).values(
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=48)
        )
    )
    await db.commit()

    async def _fake(place_id, **kwargs):
        return await _fake_details(place_id, rating=4.5, review_count=450, types=["restaurant"])

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(
        db, TENANT, ["saved:cache-2"], days=30
    ))[0]
    assert result["available"] is True
    assert result["metrics"]["avg_rating"] == 4.5
    await db.refresh(saved)
    assert saved.rating == 4.5
    assert saved.types == ["restaurant"]
    # The row's snapshot baseline still counts: compare read the stored row.
    assert saved.fetched_at and saved.fetched_at.replace(
        tzinfo=timezone.utc
    ) > datetime.now(timezone.utc) - timedelta(minutes=5)


async def test_live_range_always_calls_places_even_when_fresh(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="cache-3", label="Live Rival", rating=4.0, review_count=100
    )

    calls = []
    async def _fake(place_id, **kwargs):
        calls.append(place_id)
        return await _fake_details(place_id, rating=4.3, review_count=120)

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(db, TENANT, ["saved:cache-3"]))[0]
    assert result["available"] is True
    assert calls == ["cache-3"]            # "Live" is genuinely live
    await db.refresh(saved)
    assert saved.rating == 4.3


async def test_cache_disabled_always_calls_places(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    saved = await bench_service.save_place(
        db, TENANT, place_id="cache-4", label="Uncached Rival", rating=4.0, review_count=100
    )
    await bench_service.update_config(db, place_cache_enabled=False)

    async def _fake(place_id, **kwargs):
        return await _fake_details(place_id, rating=4.6, review_count=150)

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(
        db, TENANT, ["saved:cache-4"], days=30
    ))[0]
    assert result["available"] is True
    assert result["metrics"]["avg_rating"] == 4.6
    await db.refresh(saved)
    # Cache disabled: the live read still happened, but nothing was written.
    assert saved.rating == 4.0


async def test_saved_subject_period_from_snapshot_delta(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service
    from app.modules.benchmark.models import BenchmarkSnapshot

    saved = await bench_service.save_place(
        db, TENANT, place_id="period-1", label="Period Rival",
        rating=4.0, review_count=800,
    )
    now = datetime.now(timezone.utc)
    db.add(BenchmarkSnapshot(
        place_id=saved.id, tenant_id=TENANT, rating=4.0, review_count=800,
        fetched_at=now - timedelta(days=35),
    ))
    await db.commit()

    async def _fake(place_id, **kwargs):
        return await _fake_details(
            place_id, rating=4.4, review_count=900,
            reviews=[{
                "rating": 5, "text": "great",
                "publish_time": (now - timedelta(days=5)).isoformat(),
            }],
        )

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(
        db, TENANT, ["saved:period-1"], days=30
    ))[0]

    metrics = result["metrics"]
    assert metrics["period_reviews"] == 100          # 900 now - 800 at baseline
    assert metrics["period_avg_rating"] == 5.0       # sample average in window
    assert metrics["rating_change"] == 0.4           # 4.4 now - 4.0 at baseline
    assert metrics["period_impressions"] is None     # never exposed for competitors
    assert any("start of this period" in note for note in result["notes"])


async def test_saved_subject_period_without_history_is_null(db, monkeypatch):
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(db, TENANT, place_id="period-2", label="No History")

    async def _fake(place_id, **kwargs):
        return await _fake_details(place_id)

    monkeypatch.setattr(places_module, "get_place", _fake)
    result = (await compare.compare_subjects(
        db, TENANT, ["saved:period-2"], days=90
    ))[0]

    assert result["metrics"]["period_reviews"] is None
    assert result["metrics"]["rating_change"] is None
    assert any(
        "not enough data" in note for note in result["notes"]
    )


async def test_own_subject_period_uses_review_and_performance_rows(
    db, channel_id, user_id
):
    from app.modules.analytics.models import LocationDailyMetric, ReviewInsight

    now = datetime.now(timezone.utc)
    db.add_all([
        ReviewInsight(
            id="ri-recent", user_id=user_id, channel_id=channel_id,
            review_id="r-recent", rating=5, review_text="great",
            review_updated_at=now - timedelta(days=5),
        ),
        ReviewInsight(
            id="ri-old", user_id=user_id, channel_id=channel_id,
            review_id="r-old", rating=3, review_text="ok",
            review_updated_at=now - timedelta(days=90),
        ),
        LocationDailyMetric(
            id="ldm-in", user_id=user_id, channel_id=channel_id,
            date=(now - timedelta(days=3)).date(),
            impressions_maps_desktop=70, impressions_maps_mobile=30,
            call_clicks=4,
        ),
        LocationDailyMetric(
            id="ldm-out", user_id=user_id, channel_id=channel_id,
            date=(now - timedelta(days=40)).date(),
            impressions_maps_desktop=1000, impressions_maps_mobile=0,
            call_clicks=9,
        ),
    ])
    await db.commit()

    result = (await compare.compare_subjects(
        db, user_id, [f"own:{channel_id}"], days=30
    ))[0]
    metrics = result["metrics"]

    assert metrics["total_reviews"] == 2             # live totals untouched
    assert metrics["period_reviews"] == 1
    assert metrics["period_avg_rating"] == 5.0
    assert metrics["rating_change"] == 1.0           # 4.0 now vs 3.0 before window
    assert metrics["period_impressions"] == 100      # 40-day row is outside
    assert metrics["period_calls"] == 4
    assert any("last 30 days" in note for note in result["notes"])


async def test_own_period_performance_is_null_without_synced_rows(
    db, channel_id, user_id
):
    result = (await compare.compare_subjects(
        db, user_id, [f"own:{channel_id}"], days=30
    ))[0]
    # No rows means "not synced yet" — a zero would claim zero views.
    assert result["metrics"]["period_impressions"] is None
    assert result["metrics"]["period_calls"] is None


# ── History endpoint data ──────────────────────────────────────────────────

async def test_saved_history_is_sampled_oldest_first_and_tenant_scoped(db):
    from app.modules.benchmark import service as bench_service
    from app.modules.benchmark.models import BenchmarkSnapshot

    saved = await bench_service.save_place(
        db, TENANT, place_id="hist-1", label="History Rival"
    )
    now = datetime.now(timezone.utc)
    for offset in (1, 5, 10, 20, 40):
        db.add(BenchmarkSnapshot(
            place_id=saved.id, tenant_id=TENANT, rating=4.0,
            review_count=100 + offset, fetched_at=now - timedelta(days=offset),
        ))
    await db.commit()

    body = await compare.subject_history(
        db, TENANT, ["saved:hist-1"], days=90, points=3
    )
    series = body["subjects"][0]
    assert series["name"] == "History Rival"
    assert 1 <= len(series["points"]) <= 3
    ats = [point["at"] for point in series["points"]]
    assert ats == sorted(ats), "history reads oldest first"

    other = await compare.subject_history(
        db, "other-tenant", ["saved:hist-1"], days=90, points=3
    )
    assert other["subjects"][0]["points"] == []


async def test_saved_history_only_returns_the_selected_window(db):
    """History outside the selected period is not shown in it."""
    from app.modules.benchmark import service as bench_service
    from app.modules.benchmark.models import BenchmarkSnapshot

    saved = await bench_service.save_place(
        db, TENANT, place_id="hist-window", label="Window Rival"
    )
    now = datetime.now(timezone.utc)
    for offset in (40, 10):
        db.add(BenchmarkSnapshot(
            place_id=saved.id, tenant_id=TENANT, rating=4.1,
            review_count=100 + offset, fetched_at=now - timedelta(days=offset),
        ))
    await db.commit()

    body = await compare.subject_history(
        db, TENANT, ["saved:hist-window"], days=30, points=12
    )
    points = body["subjects"][0]["points"]
    assert any(point["reviews"] == 110 for point in points)
    # The 40-day snapshot is outside the window and must not leak into it.
    oldest = min(datetime.fromisoformat(point["at"]).replace(tzinfo=timezone.utc) for point in points)
    assert oldest >= now - timedelta(days=30)


async def test_own_history_is_cumulative(db, channel_id, user_id):
    from app.modules.analytics.models import ReviewInsight

    now = datetime.now(timezone.utc)
    db.add_all([
        ReviewInsight(
            id="ri-h1", user_id=user_id, channel_id=channel_id,
            review_id="r-h1", rating=5,
            review_updated_at=now - timedelta(days=5),
        ),
        ReviewInsight(
            id="ri-h2", user_id=user_id, channel_id=channel_id,
            review_id="r-h2", rating=3,
            review_updated_at=now - timedelta(days=90),
        ),
    ])
    await db.commit()

    body = await compare.subject_history(
        db, user_id, [f"own:{channel_id}"], days=30, points=4
    )
    series = body["subjects"][0]
    assert series["name"] == "Test Burgers"
    assert series["points"], "at least one checkpoint must be returned"
    assert series["points"][-1]["reviews"] == 2       # lifetime total by now
    assert series["points"][-1]["rating"] == 4.0


# ── Admin-editable scraper settings ────────────────────────────────────────

async def test_config_changes_are_bounded_and_persist(db):
    from app.modules.benchmark import service as bench_service

    for bad in (
        {"refresh_hours": 0},
        {"refresh_hours": 169},
        {"retention_days": 6},
        {"retention_days": 3651},
        {"nonsense": 5},
    ):
        with pytest.raises(bench_service.BenchError):
            await bench_service.update_config(db, **bad)

    row = await bench_service.update_config(
        db, refresh_hours=6, retention_days=90, place_cache_enabled=False
    )
    assert (row.refresh_hours, row.retention_days) == (6, 90)
    assert row.place_cache_enabled is False

    reloaded = await bench_service.get_config(db)
    assert (reloaded.refresh_hours, reloaded.retention_days) == (6, 90)
    assert bench_service.serialize_config(reloaded)["place_cache_enabled"] is False


# ── Scheduled scraper ──────────────────────────────────────────────────────

async def test_scraper_scrapes_due_places_records_failures_and_prunes(db, monkeypatch):
    from sqlalchemy import func, select

    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import scraper
    from app.modules.benchmark import service as bench_service
    from app.modules.benchmark.models import BenchmarkPlace, BenchmarkSnapshot

    await bench_service.update_config(
        db, refresh_hours=1, retention_days=7, place_cache_enabled=True
    )

    # Created directly, not through save_place: saving writes a snapshot at
    # "now", which would make every place look freshly scraped.
    ok = BenchmarkPlace(id="pk-scrape-ok", tenant_id=TENANT, place_id="scrape-ok", label="OK")
    bad = BenchmarkPlace(id="pk-scrape-bad", tenant_id=TENANT, place_id="scrape-bad", label="Bad")
    fresh = BenchmarkPlace(id="pk-scrape-fresh", tenant_id=TENANT, place_id="scrape-fresh", label="Fresh")
    old = BenchmarkPlace(id="pk-scrape-old", tenant_id=TENANT, place_id="scrape-old", label="Old")
    db.add_all([ok, bad, fresh, old])

    now = datetime.now(timezone.utc)
    db.add_all([
        # Scraped ten minutes ago: not due at a one-hour cadence.
        BenchmarkSnapshot(
            place_id=fresh.id, tenant_id=TENANT, rating=4.0,
            review_count=10, fetched_at=now - timedelta(minutes=10),
        ),
        # Due, and its only snapshot is older than the 7-day retention.
        BenchmarkSnapshot(
            place_id=old.id, tenant_id=TENANT, rating=4.0,
            review_count=5, fetched_at=now - timedelta(days=30),
        ),
    ])
    await db.commit()

    seen: list[str] = []

    async def _fake(place_id, **kwargs):
        seen.append(place_id)
        if place_id == "scrape-bad":
            raise places_module.PlacesError("quota exceeded", status_code=500)
        return await _fake_details(place_id, rating=4.6, review_count=12)

    monkeypatch.setattr(places_module, "get_place", _fake)
    monkeypatch.setattr(places_module, "configured", lambda: True)
    result = await scraper.refresh_due_places(now=now)

    assert result["scraped"] == 2       # ok + old
    assert result["failed"] == 1        # bad
    assert result["pruned"] >= 1
    assert "scrape-fresh" not in seen   # not due

    await db.refresh(ok)
    await db.refresh(bad)
    assert ok.review_count == 12 and ok.last_scrape_error is None
    assert bad.last_scrape_error == "quota exceeded"

    stored = (
        await db.execute(
            select(func.count()).select_from(BenchmarkSnapshot).where(
                BenchmarkSnapshot.place_id == ok.id
            )
        )
    ).scalar()
    assert stored == 1
    # The 30-day-old snapshot fell outside retention.
    ancient = (
        await db.execute(
            select(func.count()).select_from(BenchmarkSnapshot).where(
                BenchmarkSnapshot.fetched_at < now - timedelta(days=7)
            )
        )
    ).scalar()
    assert ancient == 0


async def test_scraper_can_be_paused_by_admin(db):
    from app.modules.benchmark import scraper
    from app.modules.benchmark import service as bench_service

    await bench_service.update_config(db, place_cache_enabled=False)
    result = await scraper.refresh_due_places()
    assert result["scraped"] == 0
    assert result["reason"] == "scraping disabled"


# ── HTTP surface ───────────────────────────────────────────────────────────

async def test_reviews_endpoint_own_rows(client, db, channel_id, user_id):
    """The reviews table reads the tenant's own-location reviews from analytics,
    newest first, with sentiment, time and rating."""
    now = datetime.now(timezone.utc)
    db.add_all([
        ReviewInsight(
            id="ri-rev-1", user_id=user_id, channel_id=channel_id,
            review_id="rv-review-1", rating=5, review_text="staff were great",
            sentiment="positive", review_updated_at=now - timedelta(days=2),
            replied=True,
        ),
        ReviewInsight(
            id="ri-rev-2", user_id=user_id, channel_id=channel_id,
            review_id="rv-review-2", rating=1, review_text="terrible parking",
            sentiment="negative", review_updated_at=now - timedelta(days=5),
        ),
    ])
    await db.commit()

    res = client.get(f"/api/v1/benchmark/reviews?subjects=own:{channel_id}&limit=10")
    assert res.status_code == 200, res.text
    subj = res.json()["subjects"][0]
    assert subj["name"] == "Test Burgers"
    assert len(subj["reviews"]) == 2
    newest = subj["reviews"][0]
    assert newest["rating"] == 5
    assert newest["sentiment"] == "positive"
    assert newest["time"]
    assert newest["text"] == "staff were great"
    assert newest["answered"] is True
    assert subj["summary"] == {
        "total": 2, "sampled": 2, "answered": 1,
        "unanswered": 1, "response_rate": 50.0,
        "evidence_basis": "stored_lifetime",
    }
    oldest = subj["reviews"][1]
    assert oldest["rating"] == 1
    assert oldest["sentiment"] == "negative"
    assert oldest["text"] == "terrible parking"


async def test_reviews_endpoint_saved_place_cached_sample(client, db, user_id):
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(
        db, user_id, place_id="reviews-1", label="Rev Rival",
        rating=4.0, review_count=5,
    )
    res = client.get("/api/v1/benchmark/reviews?subjects=saved:reviews-1")
    assert res.status_code == 200, res.text
    assert res.json()["subjects"][0]["name"] == "Rev Rival"
    assert res.json()["subjects"][0]["reviews"] == []
    assert res.json()["subjects"][0]["summary"] == {
        "total": 5, "sampled": 0, "answered": 0,
        "unanswered": 0, "response_rate": None,
        "evidence_basis": "cached_sample",
    }


async def test_reviews_endpoint_bounds_and_unknown_subject(client):
    assert client.get(
        "/api/v1/benchmark/reviews?subjects=own:abc&limit=0"
    ).status_code == 422
    subjects = "&".join(["subjects=own:abc"] * 7)
    assert client.get(f"/api/v1/benchmark/reviews?{subjects}").status_code == 422
    # Unknown subjects come back empty rather than failing the table.
    res = client.get("/api/v1/benchmark/reviews?subjects=unknown:zzz")
    assert res.status_code == 200
    assert res.json()["subjects"][0]["reviews"] == []


async def test_reviews_endpoint_scoped_to_other_tenant(client, other_user_id):
    res = client.get(f"/api/v1/benchmark/reviews?subjects=own:{other_user_id}")
    assert res.status_code == 200
    assert res.json()["subjects"][0]["reviews"] == []


async def test_compare_endpoint_accepts_range(client, monkeypatch):
    from app.modules.benchmark import places as places_module

    created = client.post(
        "/api/v1/benchmark/places", json={"place_id": "http-range", "label": "Range Rival"}
    )
    assert created.status_code == 201, created.text

    async def _fake_get_place(place_id, **kwargs):
        return await _fake_details(place_id, rating=4.2, review_count=42)

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    res = client.get(
        "/api/v1/benchmark/compare?subjects=saved%3Ahttp-range&range=90d"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["range"] == "90d"
    assert body["days"] == 90
    assert body["subjects"][0]["metrics"]["period_reviews"] is None

    bad = client.get(
        "/api/v1/benchmark/compare?subjects=saved%3Ahttp-range&range=week"
    )
    assert bad.status_code == 422


async def test_history_endpoint_is_bounded_and_tenant_scoped(client):
    res = client.get(
        "/api/v1/benchmark/history?subjects=saved%3Amissing&days=30&points=5"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["days"] == 30
    assert body["subjects"][0]["points"] == []

    too_many = client.get(
        "/api/v1/benchmark/history?subjects=saved%3Amissing&days=30&points=99"
    )
    assert too_many.status_code == 422


# ── Cohort tags on own subjects ────────────────────────────────────────────

async def _tagged_channel(db, user_id, channel_pk, metadata_json):
    """A google_reviews channel whose metadata carries the given raw JSON."""
    from app.modules.channels.models import Channel

    channel = Channel(
        id=channel_pk, user_id=user_id, platform="google_reviews",
        platform_user_id="acct-tags", display_name="Tagged Branch",
        status="active", metadata_json=metadata_json,
    )
    db.add(channel)
    await db.commit()
    return channel_pk


async def test_own_subject_tags_are_normalized(db, user_id):
    """Tags come from channel metadata, normalized: trimmed and lowercased,
    deduplicated, capped at 5 tags of at most 30 characters each, with junk
    entries dropped rather than crashing the comparison."""
    metadata = json.dumps({
        "location_id": "loc-tags",
        "tags": [
            "  Cafes ", "FAMILY", "family", "Riyadh", "x" * 40,
            "sixth", "   ", 123, {"not": "a tag"},
        ],
    })
    channel_pk = await _tagged_channel(db, user_id, "ch-tags-norm", metadata)

    result = (await compare.compare_subjects(db, user_id, [f"own:{channel_pk}"]))[0]

    assert result["available"] is True
    assert result["tags"] == ["cafes", "family", "riyadh", "x" * 30, "sixth"]


async def test_own_subject_without_tags_is_empty_list(db, user_id):
    """No tags key, an empty list, a non-list value, malformed JSON and no
    metadata at all all mean "no cohort": an empty list, never None."""
    no_key = await _tagged_channel(
        db, user_id, "ch-tags-nokey", '{"location_id": "loc-none"}'
    )
    empty = await _tagged_channel(db, user_id, "ch-tags-empty", '{"tags": []}')
    not_a_list = await _tagged_channel(db, user_id, "ch-tags-str", '{"tags": "cafe"}')
    malformed = await _tagged_channel(db, user_id, "ch-tags-bad", "not-json")
    no_metadata = await _tagged_channel(db, user_id, "ch-tags-nometa", None)

    for channel_pk in (no_key, empty, not_a_list, malformed, no_metadata):
        result = (await compare.compare_subjects(db, user_id, [f"own:{channel_pk}"]))[0]
        assert result["available"] is True, channel_pk
        assert result["tags"] == [], channel_pk


async def test_saved_and_unavailable_subjects_carry_empty_tags(db, monkeypatch):
    """Saved competitors have no cohort tags, and the blank record factory
    gives every record the key — even unavailable ones — so the frontend can
    read subject.tags unconditionally."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(
        db, TENANT, place_id="tags-saved", label="Tagless Rival"
    )

    async def _fake_get_place(place_id, **kwargs):
        return {"place_id": place_id, "name": "Tagless Rival", "address": None,
                "rating": 4.0, "review_count": 10, "types": [], "reviews": []}

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)
    results = await compare.compare_subjects(
        db, TENANT, ["saved:tags-saved", "own:missing-channel"]
    )

    assert results[0]["available"] is True
    assert results[0]["tags"] == []
    assert results[1]["available"] is False
    assert results[1]["tags"] == []


# ── Provider routing (google_places / boq / outscraper) ──────────────────


async def _select_source(db, source):
    """Point the benchmark config at a provider (no public setter exists)."""
    from app.modules.benchmark import service as bench_service

    config = await bench_service.get_config(db)
    config.source = source
    await db.commit()


async def test_saved_subject_boq_uses_cached_no_live_scrape(db, monkeypatch):
    """boq read paths must use the cached row, never a 600s live scrape."""
    from app.modules.benchmark import boq as boq_module
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await _select_source(db, "boq")
    row = await bench_service.save_place(
        db, TENANT, place_id="boq-1", label="Gosom Rival",
        maps_url="https://maps.google.com/?cid=1",
    )
    now = datetime.now(timezone.utc)
    await bench_service.store_place_details(db, row, {
        "name": "Gosom Rival", "address": "Riyadh", "rating": 4.6,
        "review_count": 700, "types": ["cafe"],
        "reviews": [{"rating": 5, "text": "great",
                     "publish_time": (now - timedelta(days=1)).isoformat()}],
    })

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("read path must not call a live provider")

    monkeypatch.setattr(boq_module, "get_place", _must_not_call)
    monkeypatch.setattr(places_module, "get_place", _must_not_call)

    result = (await compare.compare_subjects(db, TENANT, ["saved:boq-1"]))[0]
    assert result["available"] is True
    assert result["name"] == "Gosom Rival"
    assert result["metrics"]["avg_rating"] == 4.6
    assert result["metrics"]["total_reviews"] == 700


async def test_saved_subject_boq_no_cache_returns_last_known(db, monkeypatch):
    """With no cached details yet, boq source still returns the saved identity
    + numbers (no provider call), instead of hanging on a live scrape."""
    from app.modules.benchmark import boq as boq_module
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await _select_source(db, "boq")
    await bench_service.save_place(
        db, TENANT, place_id="boq-both", label="Offline Rival",
        rating=4.2, review_count=300,
    )

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("read path must not call a live provider")

    monkeypatch.setattr(boq_module, "get_place", _must_not_call)
    monkeypatch.setattr(places_module, "get_place", _must_not_call)

    result = (await compare.compare_subjects(db, TENANT, ["saved:boq-both"]))[0]
    assert result["available"] is True
    assert result["name"] == "Offline Rival"
    assert result["metrics"]["avg_rating"] == 4.2
    assert result["metrics"]["total_reviews"] == 300


async def test_saved_reviews_boq_serve_cached_no_live_scrape(db, monkeypatch):
    from app.modules.benchmark import boq as boq_module
    from app.modules.benchmark import service as bench_service

    await _select_source(db, "boq")
    row = await bench_service.save_place(db, TENANT, place_id="boq-rev", label="Rev Rival")
    now = datetime.now(timezone.utc)
    await bench_service.store_place_details(db, row, {
        "reviews": [
            {"rating": 5, "text": "love it",
             "owner_answer": "Thanks for the feedback",
             "owner_answer_time": (now - timedelta(days=1)).isoformat(),
             "publish_time": (now - timedelta(days=2)).isoformat()},
            {"rating": 2, "text": "bad",
             "publish_time": (now - timedelta(days=3)).isoformat()},
        ],
    })

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("read path must not call a live provider")

    monkeypatch.setattr(boq_module, "get_place", _must_not_call)

    body = await compare.reviews_for(db, TENANT, ["saved:boq-rev"], limit=10)
    subj = body["subjects"][0]
    assert subj["name"] == "Rev Rival"
    assert len(subj["reviews"]) == 2
    assert subj["reviews"][0]["rating"] == 5
    assert subj["reviews"][0]["answered"] is True
    assert subj["reviews"][0]["owner_answer"] == "Thanks for the feedback"
    assert subj["summary"]["sampled"] == 2
    assert subj["summary"]["answered"] == 1
    assert subj["summary"]["unanswered"] == 1
    assert subj["summary"]["response_rate"] == 50.0
    assert subj["summary"]["evidence_basis"] == "cached_sample"


async def test_saved_subject_uses_outscraper_when_selected(db, monkeypatch):
    from app.modules.benchmark import outscraper as outscraper_module
    from app.modules.benchmark import service as bench_service

    await _select_source(db, "outscraper")
    await bench_service.save_place(db, TENANT, place_id="out-1", label="Out Rival")

    seen: dict = {}

    async def _fake_outscraper(place_id, **kwargs):
        seen.update(kwargs)
        return {
            "place_id": place_id, "name": "Out Rival", "address": None,
            "rating": 4.1, "review_count": 55, "types": [], "reviews": [],
        }

    monkeypatch.setattr(outscraper_module, "get_place", _fake_outscraper)
    monkeypatch.setattr(outscraper_module, "configured", lambda: True)

    result = (await compare.compare_subjects(db, TENANT, ["saved:out-1"]))[0]

    assert result["available"] is True
    assert result["name"] == "Out Rival"
    assert seen["reviews_limit"] == 10
    assert "cutoff" in seen
