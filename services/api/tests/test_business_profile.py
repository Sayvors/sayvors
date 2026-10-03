"""Business profile card: generation, edit-wins semantics, AI grounding.

No network, sqlite DB. The LLM step (_ask_llm) is mocked — the tests pin
the rules around it: auto refresh never touches edited cards, forced
regeneration only fills empty fields, and the card flows into
get_business_context / format_business_identity / prompt_block.
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.profile import business_profile as bp
from app.modules.profile.business_profile import (
    _parse_profile_json,
    generate_business_profile,
    get_business_profile_row,
    prompt_block,
    save_business_profile,
)
from app.modules.profile.service import (
    format_business_identity,
    get_business_context,
)

LLM_FIELDS = {
    "summary": "Charcoal grill restaurant known for shawarma.",
    "domain": "Food & Restaurant",
    "products_services": "shawarma, mixed grill, falafel",
    "not_offered_and_policies": "No alcohol; halal only.",
    "audience_languages": "Families and office lunch crowds; Arabic and English.",
}


def _mock_llm(monkeypatch, fields=LLM_FIELDS):
    async def _fake_ask(material, user_id, db):
        return dict(fields)

    monkeypatch.setattr(bp, "_ask_llm", _fake_ask)


async def _make_user(db, user_id, **fields):
    from app.modules.users.models import User

    user = User(
        id=user_id,
        first_name="Test",
        last_name="Owner",
        email=f"{user_id}@example.com",
        password_hash="x",
        **fields,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_generate_creates_auto_card(db, user_id, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")
    _mock_llm(monkeypatch)

    profile = await generate_business_profile(user_id, db)

    assert profile["source"] == "auto"
    assert "shawarma" in profile["summary"]
    row = await get_business_profile_row(user_id, db)
    assert row is not None and row.generated_at is not None


@pytest.mark.asyncio
async def test_generate_requires_material(db, user_id, monkeypatch):
    await _make_user(db, user_id)
    _mock_llm(monkeypatch)
    with pytest.raises(ValueError):
        await generate_business_profile(user_id, db)


@pytest.mark.asyncio
async def test_edited_card_is_never_auto_refreshed(db, user_id, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")
    await save_business_profile(
        user_id, {"summary": "MY OWN summary", "domain": "My domain"}, db
    )
    _mock_llm(monkeypatch)

    profile = await generate_business_profile(user_id, db, force=False)

    assert profile["summary"] == "MY OWN summary"
    assert profile["domain"] == "My domain"
    assert profile["source"] == "edited"


@pytest.mark.asyncio
async def test_forced_regeneration_keeps_user_text_fills_empty(db, user_id, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")
    await save_business_profile(
        user_id, {"summary": "MY OWN summary", "domain": "My domain"}, db
    )
    _mock_llm(monkeypatch)

    profile = await generate_business_profile(user_id, db, force=True)

    # user text survives, empty fields get filled from the LLM
    assert profile["summary"] == "MY OWN summary"
    assert profile["domain"] == "My domain"
    assert profile["products_services"] == LLM_FIELDS["products_services"]
    assert profile["not_offered_and_policies"] == LLM_FIELDS["not_offered_and_policies"]


@pytest.mark.asyncio
async def test_auto_card_is_refreshed_on_new_ingest(db, user_id, monkeypatch):
    from datetime import datetime, timedelta, timezone

    await _make_user(db, user_id, business_sells="shawarma")
    _mock_llm(monkeypatch, {**LLM_FIELDS, "summary": "Old summary"})
    await generate_business_profile(user_id, db)

    # Age the card past the refresh cooldown, as a later ingest job would.
    row = await get_business_profile_row(user_id, db)
    row.generated_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    await db.commit()

    _mock_llm(monkeypatch, {**LLM_FIELDS, "summary": "FRESH summary"})
    profile = await generate_business_profile(user_id, db, force=False)

    assert profile["summary"] == "FRESH summary"
    assert profile["source"] == "auto"


@pytest.mark.asyncio
async def test_auto_refresh_cooldown_skips_second_call(db, user_id, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")
    _mock_llm(monkeypatch, {**LLM_FIELDS, "summary": "First"})
    await generate_business_profile(user_id, db)

    calls = {"n": 0}

    async def _counting_ask(material, user_id_, db_):
        calls["n"] += 1
        return {**LLM_FIELDS, "summary": "Second"}

    monkeypatch.setattr(bp, "_ask_llm", _counting_ask)
    profile = await generate_business_profile(user_id, db, force=False)

    assert calls["n"] == 0  # debounced, no LLM call
    assert profile["summary"] == "First"


@pytest.mark.asyncio
async def test_card_flows_into_business_context_and_identity(db, user_id, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")
    _mock_llm(monkeypatch)
    await generate_business_profile(user_id, db)

    ctx = await get_business_context(user_id, db)
    assert ctx["business_summary"].startswith("Charcoal grill")
    assert ctx["business_not_offered_and_policies"] == "No alcohol; halal only."

    text = format_business_identity(ctx)
    assert "Summary:" in text and "Charcoal grill" in text
    assert "Does NOT offer / policies:" in text and "halal" in text


@pytest.mark.asyncio
async def test_prompt_block_and_missing_user(db, user_id, monkeypatch):
    assert await prompt_block(None, db) == ""
    assert await prompt_block("no-such-user", db) == ""

    await _make_user(db, user_id, business_sells="shawarma")
    _mock_llm(monkeypatch)
    await generate_business_profile(user_id, db)

    block = await prompt_block(user_id, db)
    assert block.startswith("Business profile (")
    assert "shawarma, mixed grill" in block
    assert "Arabic and English" in block


def test_parse_profile_json_tolerates_prose_and_fences():
    raw = 'Here you go:\n```json\n{"summary": "S", "domain": "D", "junk": 1}\n```\nDone.'
    data = _parse_profile_json(raw)
    assert data == {"summary": "S", "domain": "D"}
    with pytest.raises(ValueError):
        _parse_profile_json("no json at all")


@pytest.mark.asyncio
async def test_profile_endpoints(db, user_id, client, monkeypatch):
    await _make_user(db, user_id, business_sells="shawarma")

    r = client.get("/api/v1/profile/business")
    assert r.status_code == 200 and r.json()["profile"] is None

    r = client.put(
        "/api/v1/profile/business",
        json={"summary": "Hand-written", "domain": "Retail"},
    )
    assert r.status_code == 200
    assert r.json()["profile"]["source"] == "edited"

    # an all-empty save must not create a generation-proof empty row
    r = client.put(
        "/api/v1/profile/business",
        json={"summary": "", "domain": "", "products_services": "",
              "not_offered_and_policies": "", "audience_languages": ""},
    )
    assert r.status_code == 400

    _mock_llm(monkeypatch)
    r = client.post("/api/v1/profile/business/regenerate")
    assert r.status_code == 200
    body = r.json()["profile"]
    assert body["summary"] == "Hand-written"  # edit wins
    assert body["products_services"] == LLM_FIELDS["products_services"]

    r = client.get("/api/v1/profile/business")
    assert r.json()["profile"]["domain"] == "Retail"
