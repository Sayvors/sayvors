"""Bench service: tenant scoping, idempotency and hard caps."""
import pytest

from app.modules.benchmark import service

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant-bench-a"
TENANT_B = "tenant-bench-b"


async def test_save_is_idempotent_and_updates_notes(db):
    first = await service.save_place(
        db, TENANT_A, place_id="p1", label="First", notes="hello"
    )
    again = await service.save_place(
        db, TENANT_A, place_id="p1", label="Renamed", notes="updated"
    )
    assert again.id == first.id
    assert again.label == "Renamed" and again.notes == "updated"
    assert len(await service.list_saved(db, TENANT_A)) == 1


async def test_list_and_delete_are_tenant_scoped(db):
    await service.save_place(db, TENANT_A, place_id="p1")
    await service.save_place(db, TENANT_B, place_id="p2")

    assert [p["place_id"] for p in await service.list_saved(db, TENANT_A)] == ["p1"]
    assert [p["place_id"] for p in await service.list_saved(db, TENANT_B)] == ["p2"]

    assert await service.delete_saved(db, TENANT_A, "p2") is False
    assert await service.delete_saved(db, TENANT_A, "p1") is True
    assert await service.list_saved(db, TENANT_A) == []
    assert len(await service.list_saved(db, TENANT_B)) == 1


async def test_cap_enforced(db):
    config = await service.get_config(db)
    config.max_saved_places = 2
    await db.commit()
    await service.save_place(db, TENANT_A, place_id="p1")
    await service.save_place(db, TENANT_A, place_id="p2")
    with pytest.raises(service.BenchError, match="bench holds"):
        await service.save_place(db, TENANT_A, place_id="p3")


async def test_blank_place_rejected(db):
    with pytest.raises(service.BenchError):
        await service.save_place(db, TENANT_A, place_id="  ")


async def test_save_writes_day_one_snapshot(db):
    await service.save_place(
        db, TENANT_A, place_id="p1", rating=4.5, review_count=120
    )
    matrix = await service.heatmap_matrix(db, TENANT_A, weeks=2)
    assert len(matrix["weeks"]) == 2
    assert len(matrix["rows"]) == 1
    populated = [v for v in matrix["rows"][0]["cells"] if v is not None]
    assert populated == [120]


async def test_heatmatrix_empty_when_nothing_saved(db):
    matrix = await service.heatmap_matrix(db, TENANT_B, weeks=4)
    assert matrix["rows"] == []
    assert len(matrix["weeks"]) == 4


# -- HTTP surface -------------------------------------------------------------

pytestmark = pytest.mark.asyncio


async def test_search_requires_permission(client, db, monkeypatch):
    import app.modules.benchmark.places as places_module

    config = await service.get_config(db)
    config.source = "google_places"
    await db.commit()
    monkeypatch.setattr(places_module, "configured", lambda: True)

    async def _fake(query, **kwargs):
        return [{"place_id": "p1", "name": "Cafe", "address": None,
                 "rating": 4.5, "review_count": 10, "types": []}]

    monkeypatch.setattr(places_module, "search_places", _fake)
    res = client.get("/api/v1/benchmark/search?q=cafe")
    assert res.status_code == 200
    body = res.json()
    assert body["nearby"][0]["place_id"] == "p1"


async def test_save_and_list_are_tenant_scoped(client, db):
    res = client.post("/api/v1/benchmark/places", json={"place_id": "p1", "label": "Cafe"})
    assert res.status_code == 201, res.text
    listed = client.get("/api/v1/benchmark/places")
    assert listed.status_code == 200
    assert any(p["place_id"] == "p1" for p in listed.json())

    deleted = client.delete("/api/v1/benchmark/places/p1")
    assert deleted.status_code == 200
    assert client.get("/api/v1/benchmark/places").json() == []


async def test_delete_other_tenant_place_returns_404(client, db):
    assert client.delete("/api/v1/benchmark/places/not-mine").status_code == 404


async def test_save_returns_not_ready_then_refresh_makes_ready(client, db, monkeypatch):
    import app.modules.benchmark.places as places_module

    config = await service.get_config(db)
    config.source = "google_places"
    await db.commit()
    monkeypatch.setattr(places_module, "configured", lambda: True)

    async def _fake_get_place(place_id, **kwargs):
        assert kwargs.get("reviews_limit") == 10
        assert "cutoff" in kwargs
        return {
            "place_id": place_id, "name": "Cafe", "address": "Riyadh",
            "rating": 4.5, "review_count": 20, "types": ["cafe"],
            "reviews": [{"rating": 5, "text": "Great"}],
        }

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)

    res = client.post("/api/v1/benchmark/places", json={"place_id": "p-ready", "label": "Cafe"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["fetched_at"] is None
    assert body["last_scrape_error"] is None

    ref = client.post("/api/v1/benchmark/places/p-ready/refresh")
    assert ref.status_code == 200, ref.text
    ready = ref.json()
    assert ready["fetched_at"] is not None
    assert ready["last_scrape_error"] is None
    assert ready["name"] == "Cafe"


# -- maps_url / reviews_per_score --------------------------------------------

async def test_save_place_stores_maps_url_and_serializes_new_fields(db):
    row = await service.save_place(
        db, TENANT_A, place_id="p-maps",
        maps_url="https://maps.google.com/?cid=99",
    )
    assert row.maps_url == "https://maps.google.com/?cid=99"
    data = service.serialize(row)
    assert data["maps_url"] == "https://maps.google.com/?cid=99"
    assert data["reviews_per_score"] is None

    # Updating a duplicate with a new URL overwrites it.
    again = await service.save_place(
        db, TENANT_A, place_id="p-maps",
        maps_url="https://maps.google.com/?cid=100",
    )
    assert again.id == row.id
    assert again.maps_url == "https://maps.google.com/?cid=100"

    # Omitting maps_url on a duplicate leaves the stored value intact.
    kept = await service.save_place(db, TENANT_A, place_id="p-maps")
    assert kept.maps_url == "https://maps.google.com/?cid=100"


async def test_save_place_truncates_oversized_maps_url(db):
    row = await service.save_place(
        db, TENANT_A, place_id="p-long", maps_url="x" * 5000
    )
    assert len(row.maps_url) == service.MAX_MAPS_URL


async def test_store_place_details_records_reviews_per_score(db):
    row = await service.save_place(
        db, TENANT_A, place_id="p-rps", rating=4.0, review_count=10
    )
    await service.store_place_details(
        db, row,
        {"rating": 4.3, "review_count": 20, "reviews_per_score": {"5": 15, "1": 5}},
    )
    await db.refresh(row)
    assert row.reviews_per_score == {"5": 15, "1": 5}
    assert row.rating == 4.3

    # A payload without reviews_per_score leaves the stored value intact.
    await service.store_place_details(db, row, {"rating": 4.4})
    await db.refresh(row)
    assert row.reviews_per_score == {"5": 15, "1": 5}


# -- Provider routing on the refresh / details endpoints ---------------------

async def _select_source(db, source):
    config = await service.get_config(db)
    config.source = source
    await db.commit()


async def test_refresh_uses_boq_when_selected(client, db, monkeypatch):
    import app.modules.benchmark.boq as boq_module
    import app.modules.benchmark.places as places_module

    await _select_source(db, "boq")
    res = client.post(
        "/api/v1/benchmark/places", json={"place_id": "g-ready", "label": "G"}
    )
    assert res.status_code == 201, res.text

    async def _fake_boq(place_id, **kwargs):
        return {
            "place_id": place_id, "name": "G Cafe", "address": "Riyadh",
            "rating": 4.7, "review_count": 33, "types": [], "reviews": [],
            "reviews_per_score": {"5": 20},
        }

    monkeypatch.setattr(boq_module, "get_place", _fake_boq)

    async def _places_unavailable(*args, **kwargs):
        raise places_module.PlacesError("no key", 503)

    monkeypatch.setattr(places_module, "get_place", _places_unavailable)

    ref = client.post("/api/v1/benchmark/places/g-ready/refresh")
    assert ref.status_code == 200, ref.text
    body = ref.json()
    assert body["name"] == "G Cafe"
    assert body["reviews_per_score"] == {"5": 20}


async def test_refresh_falls_back_to_places_when_boq_fails(client, db, monkeypatch):
    import app.modules.benchmark.boq as boq_module
    import app.modules.benchmark.places as places_module

    await _select_source(db, "boq")
    client.post("/api/v1/benchmark/places", json={"place_id": "g-fb", "label": "FB"})

    async def _boq_boom(place_id, **kwargs):
        raise boq_module.BoqError("boq down", status_code=502)

    async def _places_ok(place_id, **kwargs):
        return {
            "place_id": place_id, "name": "FB Cafe", "address": None,
            "rating": 4.0, "review_count": 5, "types": [], "reviews": [],
        }

    monkeypatch.setattr(boq_module, "get_place", _boq_boom)
    monkeypatch.setattr(places_module, "get_place", _places_ok)
    monkeypatch.setattr(places_module, "configured", lambda: True)

    ref = client.post("/api/v1/benchmark/places/g-fb/refresh")
    assert ref.status_code == 200, ref.text
    assert ref.json()["name"] == "FB Cafe"


async def test_refresh_records_error_when_all_providers_fail(client, db, user_id, monkeypatch):
    import app.modules.benchmark.boq as boq_module
    import app.modules.benchmark.places as places_module

    await _select_source(db, "boq")
    client.post("/api/v1/benchmark/places", json={"place_id": "g-err", "label": "Err"})

    async def _boq_boom(place_id, **kwargs):
        raise boq_module.BoqError("boq down", status_code=502)

    async def _places_boom(place_id, **kwargs):
        raise places_module.PlacesError("places down", status_code=503)

    monkeypatch.setattr(boq_module, "get_place", _boq_boom)
    monkeypatch.setattr(places_module, "get_place", _places_boom)

    ref = client.post("/api/v1/benchmark/places/g-err/refresh")
    assert ref.status_code == 502, ref.text

    saved = await service.get_saved(db, user_id, "g-err")
    assert saved is not None
    assert saved.last_scrape_error


async def test_place_details_boq_serves_cached_no_live_scrape(client, db, user_id, monkeypatch):
    """place_details must not live-scrape boq (120s+ hold killed the DB
    session); it serves the cached row the worker / refresh filled."""
    import app.modules.benchmark.boq as boq_module
    import app.modules.benchmark.places as places_module
    from app.modules.benchmark import service as bench_service

    await _select_source(db, "boq")
    row = await bench_service.save_place(db, user_id, place_id="g-det", label="Det")
    await bench_service.store_place_details(db, row, {
        "name": "Det Cafe", "rating": 4.9, "review_count": 8,
        "reviews": [{"rating": 5, "text": "nice"}],
        "thumbnail": "https://lh3.googleusercontent.com/x",
    })

    async def _must_not_call(*args, **kwargs):
        raise AssertionError("place_details must not live-scrape boq")

    monkeypatch.setattr(boq_module, "get_place", _must_not_call)

    async def _places_unavailable(*args, **kwargs):
        raise places_module.PlacesError("no key", 503)

    monkeypatch.setattr(places_module, "get_place", _places_unavailable)

    res = client.get("/api/v1/benchmark/places/g-det/details")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Det Cafe"
    assert body["rating"] == 4.9
    assert body["thumbnail"] == "https://lh3.googleusercontent.com/x"
    assert body["saved_id"]


async def test_place_details_serves_cache_when_paid_provider_has_no_key(client, db, user_id, monkeypatch):
    """Staging has no Places key by default: details must be 200, not 503."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    row = await bench_service.save_place(db, user_id, place_id="cached-no-key", label="Cached")
    await bench_service.store_place_details(db, row, {
        "name": "Cached Cafe", "rating": 4.3, "review_count": 55,
        "reviews": [{"rating": 5, "text": "great"}],
    })
    monkeypatch.setattr(places_module, "configured", lambda: False)

    async def must_not_call(*args, **kwargs):
        raise AssertionError("read handler called an unconfigured paid provider")

    monkeypatch.setattr(places_module, "get_place", must_not_call)

    res = client.get("/api/v1/benchmark/places/cached-no-key/details")

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Cached Cafe"


async def test_saving_with_search_metadata_keeps_the_photo_and_is_ready(client, db, user_id):
    res = client.post("/api/v1/benchmark/places", json={
        "place_id": "with-photo", "label": "Photo Cafe", "rating": 4.4,
        "review_count": 123, "thumbnail": "https://lh3.googleusercontent.com/cover=s256",
        "maps_url": "https://www.google.com/maps/place/X/data=!4m6!3m5!1s0x1:0x2",
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["thumbnail"] == "https://lh3.googleusercontent.com/cover=s256"
    # Identity + rating + count are already known at save time; the card must
    # not say "not ready" while the synchronous review refresh runs, without
    # pretending a detail fetch already happened.
    assert body["details_ready"] is True
    assert body["fetched_at"] is None


async def test_get_config_includes_source(client, db):
    res = client.get("/api/v1/benchmark/config")
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "boq"
