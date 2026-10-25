"""Launch checklist state lives in the database, per user.

The dashboard checklist ("Start here — launch step by step") must survive a
new device or a cleared browser, and hiding it must be a server-side decision
rather than a localStorage-only flag.
"""
import pytest
from sqlalchemy import select

from app.modules.onboarding.schemas import normalize_onboarding_state
from app.modules.users.models import User

_HOST = {"host": "localhost"}


def test_normalize_defaults():
    assert normalize_onboarding_state(None) == {
        "dismissed": False,
        "open": True,
        "steps": {},
    }


def test_normalize_accepts_booleans_and_01():
    out = normalize_onboarding_state(
        {"dismissed": 1, "open": 0, "steps": {"channel": 1, "x": 0}}
    )
    assert out == {
        "dismissed": True,
        "open": False,
        "steps": {"channel": True, "x": False},
    }


def test_normalize_falls_back_on_garbage():
    # Strings are not booleans — the safe default wins, never a truthy string.
    out = normalize_onboarding_state({"dismissed": "yes", "open": "no"})
    assert out["dismissed"] is False
    assert out["open"] is True


def test_normalize_ignores_non_dict_payloads():
    assert normalize_onboarding_state("nope")["steps"] == {}
    assert normalize_onboarding_state({"steps": ["channel"]})["steps"] == {}


async def _ensure_user(db, user_id: str) -> None:
    row = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if row is None:
        db.add(
            User(
                id=user_id,
                email=f"{user_id}@sayvors.test",
                first_name="Test",
                last_name="User",
                password_hash="x",
                onboarded=True,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_round_trip_persists_dismissed_and_steps(client, db, user_id):
    await _ensure_user(db, user_id)

    r = client.get("/api/v1/onboarding", headers=_HOST)
    assert r.status_code == 200
    assert r.json() == {"dismissed": False, "open": True, "steps": {}}

    r = client.put(
        "/api/v1/onboarding",
        json={"dismissed": True, "steps": {"channel": True}},
        headers=_HOST,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dismissed"] is True
    assert body["steps"] == {"channel": True}

    # A fresh read (the "new device" case) sees the same state.
    r = client.get("/api/v1/onboarding", headers=_HOST)
    assert r.json()["dismissed"] is True
    assert r.json()["steps"]["channel"] is True


@pytest.mark.asyncio
async def test_merges_steps_instead_of_replacing(client, db, user_id):
    await _ensure_user(db, user_id)

    client.put("/api/v1/onboarding", json={"steps": {"channel": True}}, headers=_HOST)
    client.put("/api/v1/onboarding", json={"steps": {"databank": True}}, headers=_HOST)

    steps = client.get("/api/v1/onboarding", headers=_HOST).json()["steps"]
    assert steps == {"channel": True, "databank": True}


@pytest.mark.asyncio
async def test_can_reopen_dismissed_checklist(client, db, user_id):
    await _ensure_user(db, user_id)

    client.put("/api/v1/onboarding", json={"dismissed": True}, headers=_HOST)
    r = client.put("/api/v1/onboarding", json={"dismissed": False}, headers=_HOST)
    assert r.json()["dismissed"] is False
