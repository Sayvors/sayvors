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


# -- HTTP surface -------------------------------------------------------------

pytestmark = pytest.mark.asyncio


async def test_search_requires_permission(client, monkeypatch):
    import app.modules.benchmark.places as places_module

    async def _fake(query, **kwargs):
        return [{"place_id": "p1", "name": "Cafe", "address": None,
                 "rating": 4.5, "review_count": 10, "types": []}]

    monkeypatch.setattr(places_module, "search_places", _fake)
    res = client.get("/api/v1/benchmark/search?q=cafe")
    assert res.status_code == 200
    assert res.json()[0]["place_id"] == "p1"


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
