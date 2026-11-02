"""Admin-managed AI personas.

Sarah is the fallback; the admin can add personas, edit name/gender/tone, and
activate exactly one. The reply prompt reads the active persona.
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.assistant.personas import (
    AIPersona,
    DEFAULT_PERSONA,
    PersonaSpec,
    get_active_persona,
    invalidate_persona_cache,
)
from app.modules.channels.meta.consumer import _system_prompt
from app.security import hash_password
from types import SimpleNamespace


def _user():
    return SimpleNamespace(
        business_name="Aster Beans",
        first_name="Aster",
        last_name="Coffee",
        business_description="A specialty coffee roaster.",
        business_sells="beans",
        business_doesnt_sell="",
    )


def test_prompt_uses_the_active_persona():
    prompt = _system_prompt(
        _user(),
        persona=PersonaSpec("Layla", "female", "Warm", "Keep replies to two sentences."),
    )
    assert "You are Layla" in prompt
    assert "You are a woman" in prompt
    assert "Keep replies to two sentences." in prompt
    assert "You are Sarah" not in prompt


def test_prompt_uses_male_and_neutral_grammar():
    male = _system_prompt(_user(), persona=PersonaSpec("Omar", "male", None, None))
    assert "You are a man" in male
    neutral = _system_prompt(_user(), persona=PersonaSpec("Nova", "neutral", None, None))
    assert "gender-neutral first-person" in neutral


def test_default_persona_is_sarah():
    assert DEFAULT_PERSONA.name == "Sarah"
    assert DEFAULT_PERSONA.gender == "female"
    assert "You are Sarah" in _system_prompt(_user())


@pytest.mark.asyncio
async def test_active_persona_is_read_from_the_db(db):
    invalidate_persona_cache()
    db.add(AIPersona(
        id="persona-layla", name="Layla", gender="female",
        description="Warm", instructions="Be brief.", is_active=True,
    ))
    await db.commit()
    spec = await get_active_persona(db)
    assert spec.name == "Layla"
    assert spec.instructions == "Be brief."


@pytest.mark.asyncio
async def test_admin_can_create_edit_activate_and_delete(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", hash_password("test-admin-pass"))
    invalidate_persona_cache()
    db.add(AIPersona(
        id="persona-sarah-test", name="Sarah", gender="female",
        description="Warm, capable support teammate", is_active=True,
    ))
    await db.commit()
    headers = {"host": "localhost", "X-Requested-With": "XMLHttpRequest"}
    login = client.post(
        "/api/v1/admin/login",
        json={"username": "admin", "password": "test-admin-pass"},
        headers=headers,
    )
    assert login.status_code == 200, login.text

    created = client.post(
        "/api/v1/admin/personas",
        json={
            "name": "Layla",
            "gender": "female",
            "description": "Warm",
            "instructions": "Keep replies short.",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    persona_id = created.json()["id"]
    assert created.json()["is_active"] is False

    activated = client.post(
        f"/api/v1/admin/personas/{persona_id}/activate", headers=headers
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["is_active"] is True

    listed = client.get("/api/v1/admin/personas", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()["personas"]
    assert sum(1 for row in rows if row["is_active"]) == 1
    assert next(row for row in rows if row["id"] == persona_id)["name"] == "Layla"

    updated = client.patch(
        f"/api/v1/admin/personas/{persona_id}",
        json={"instructions": "Use one sentence."},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["instructions"] == "Use one sentence."

    blocked = client.delete(f"/api/v1/admin/personas/{persona_id}", headers=headers)
    assert blocked.status_code == 409

    # Activate Sarah again, then Layla can be deleted.
    sarah = next(row for row in rows if row["name"] == "Sarah")
    assert client.post(
        f"/api/v1/admin/personas/{sarah['id']}/activate", headers=headers
    ).status_code == 200
    deleted = client.delete(f"/api/v1/admin/personas/{persona_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert (
        await db.execute(
            select(AIPersona.id).where(AIPersona.id == persona_id)
        )
    ).scalar_one_or_none() is None
