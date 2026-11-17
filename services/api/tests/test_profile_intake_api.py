"""Business-intake endpoints: cascade resolution and merchant-owned answers.

No network, sqlite DB. The GET endpoint must never ask what Google already
knows; the PUT endpoint must persist answers somewhere a facts rebuild cannot
erase.
"""
from sqlalchemy import select

from app.modules.profile.models import TenantIntakeAnswer
from app.modules.users.models import User


async def _seed_user(db, user_id: str) -> User:
    row = User(
        id=user_id,
        first_name="Test",
        last_name="User",
        email=f"{user_id}@example.com",
        password_hash="x",
        business_type="Retail & Shops",
    )
    db.add(row)
    await db.commit()
    return row


async def test_get_intake_resolves_stored_label_to_retail(client, db, user_id):
    await _seed_user(db, user_id)
    resp = client.get("/api/v1/profile/intake")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vertical_key"] == "retail"
    assert body["vertical_label"] == "Retail & Shops"
    assert body["sub_focus"] == "general"
    assert body["questions"]
    assert all(q["source"] != "google" for q in body["questions"])
    assert any(v["key"] == "restaurant" for v in body["verticals"])


async def test_get_intake_can_preview_another_vertical_without_saving(client, db, user_id):
    await _seed_user(db, user_id)
    resp = client.get(
        "/api/v1/profile/intake",
        params={"vertical_key": "restaurant", "sub_focus": "takeaway"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vertical_key"] == "restaurant"
    assert body["sub_focus"] == "takeaway"
    assert any(q["key"] == "service_area_detail" for q in body["questions"])
    assert any(v["key"] == "restaurant" and v["sub_focuses"] for v in body["verticals"])

    # Nothing was persisted by a preview read.
    rows = (await db.execute(select(TenantIntakeAnswer))).scalars().all()
    assert rows == []


async def test_put_intake_persists_answers_outside_the_facts_cache(client, db, user_id):
    await _seed_user(db, user_id)
    resp = client.put(
        "/api/v1/profile/intake",
        json={
            "vertical_key": "restaurant",
            "sub_focus": "dine_in",
            "answers": [
                {"question_key": "dietary", "answer": ["Halal", "Vegan"], "skipped": False},
                {"question_key": "reservations", "answer": ["By phone"], "skipped": False},
                {"question_key": "price_range", "skipped": True},
                {"question_key": "not_a_real_question", "answer": ["x"]},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vertical_key"] == "restaurant"
    assert body["sub_focus"] == "dine_in"
    by_key = {q["key"]: q for q in body["questions"]}
    assert by_key["dietary"]["answer"] == ["Halal", "Vegan"]
    assert by_key["price_range"]["skipped"] is True
    assert "not_a_real_question" not in by_key
    assert body["answered"] == 2
    assert body["skipped"] == 1

    rows = (await db.execute(select(TenantIntakeAnswer))).scalars().all()
    assert len(rows) == 3  # the unknown question was rejected
    assert all(r.tenant_id == user_id for r in rows)
    assert all(r.vertical_key == "restaurant" for r in rows)
