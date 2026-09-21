"""Tenant business context: profile fields, relevance, AI grounding.

No network, sqlite DB. Covers the owner's AI-context feature:
category/sells/doesn't-sell/description flow from the profile into the
relevance verdicts and into every AI prompt (review replies + post drafts).
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.profile.service import (
    format_business_identity,
    get_business_context,
    get_offered_services,
)


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


def _rel_analysis(product_ref=None):
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(sentiment="negative", emotion="disappointment",
                          intent=["complaint"], issue_type="product_quality",
                          product_reference=product_ref, urgency="low",
                          customer_request=None, language="en")


SHAWARMA_DOMAIN = {
    "terms": ["shawarma", "restaurant", "grill", "chicken", "falafel", "mixed"],
    "not_offered": ["shampoo", "cleaning", "alcohol"],
}


@pytest.mark.asyncio
async def test_get_business_context_returns_configured(db, user_id):
    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma, mixed grill",
                     business_doesnt_sell="shampoo, alcohol",
                     business_description="Charcoal grill spot")
    ctx = await get_business_context(user_id, db)
    assert ctx["business_type"] == "Food & Restaurant"
    assert "shawarma" in ctx["business_sells"]
    assert "shampoo" in ctx["business_doesnt_sell"]
    assert ctx["business_description"] == "Charcoal grill spot"


@pytest.mark.asyncio
async def test_get_business_context_empty_and_unknown(db, user_id):
    assert await get_business_context("no-such-user", db) == {}
    assert await get_business_context(None, db) == {}
    await _make_user(db, user_id)
    assert await get_business_context(user_id, db) == {}


def test_format_business_identity_block():
    text = format_business_identity({
        "business_name": "Beit Shawarma",
        "business_type": "Food & Restaurant",
        "business_sells": "shawarma, mixed grill",
        "business_doesnt_sell": "shampoo, alcohol",
        "business_description": "Charcoal grill spot",
    })
    assert "Beit Shawarma" in text
    assert "Food & Restaurant" in text
    assert "mixed grill" in text
    assert "Does NOT sell" in text
    assert "shampoo" in text


def test_format_business_identity_empty():
    assert format_business_identity({}) == ""
    assert format_business_identity(None) == ""


def test_shampoo_on_doesnt_sell_is_off_topic():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("is dettol shampoo available?",
                         _rel_analysis("Dettol shampoo"), SHAWARMA_DOMAIN)
    assert v["verdict"] == "off_topic"
    assert "does-not-sell" in v["reason"]


def test_shawarma_question_is_on_topic_with_sells_domain():
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("do you sell shawarma?",
                         _rel_analysis("shawarma"), SHAWARMA_DOMAIN)
    assert v["verdict"] == "on_topic"
    assert "shawarma" in v["matched_terms"]


def test_explicit_exclusion_wins_without_domain_corpus():
    """Direct tenant intent needs no minimum domain size."""
    from app.modules.review_engine.relevance import assess_relevance

    v = assess_relevance("is dettol shampoo available?",
                         _rel_analysis("Dettol shampoo"),
                         {"terms": [], "not_offered": ["shampoo"]})
    assert v["verdict"] == "off_topic"


@pytest.mark.asyncio
async def test_domain_resolution_uses_sells_excludes_no_sell(db, user_id, channel_id):
    from app.modules.review_engine.relevance import resolve_business_domain

    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma, mixed grill",
                     business_doesnt_sell="shampoo, alcohol",
                     business_description="Charcoal grill spot")
    domain = await resolve_business_domain(channel_id, user_id, db)
    assert "shawarma" in domain["terms"]
    assert "restaurant" in domain["terms"]
    # The exclusion list must never become on-topic evidence.
    assert "shampoo" not in domain["terms"]
    assert "alcohol" not in domain["terms"]
    assert "shampoo" in domain["not_offered"]
    assert "business_context" in domain["sources"]


@pytest.mark.asyncio
async def test_post_draft_prompt_carries_identity(monkeypatch, db, user_id):
    import json as _json
    from types import SimpleNamespace

    from app.modules.posts import service as _svc

    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma, mixed grill",
                     business_doesnt_sell="shampoo")
    seen = {}

    class _Provider:
        async def complete(self, req):
            seen["msg"] = req.messages[0].content
            return SimpleNamespace(content=_json.dumps({
                "description": "Try our shawarma today!",
                "tags": ["shawarma"], "keywords": ["shawarma"],
            }), finish_reason="stop")

    async def _models(db):
        return [(SimpleNamespace(id="custom:model"), None)]

    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: _Provider(),
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda mid: ("api-x", "groq"))
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models", _models)
    out = await _svc.draft_post_content(db, user_id, "Weekend shawarma deal",
                                        "offer", "Beit Shawarma")
    assert out["description"]
    assert "shawarma" in seen["msg"]
    assert "Does NOT sell" in seen["msg"]
    assert "never invent" in seen["msg"]


@pytest.mark.asyncio
async def test_post_draft_prompt_layers_databank_facts(monkeypatch, db, user_id):
    import json as _json
    from types import SimpleNamespace

    from app.modules.posts import service as _svc
    from app.modules.rag.models import Databank

    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma")
    db.add(Databank(id="bank-1", user_id=user_id, name="Menu"))
    await db.commit()
    seen = {}

    async def _fake_search(bank_id, req, user, session):
        assert bank_id == "bank-1"
        return [{"content": "Family platter SAR 89, serves four"}], False

    class _Provider:
        async def complete(self, req):
            seen["msg"] = req.messages[0].content
            return SimpleNamespace(content=_json.dumps({
                "description": "Family platter SAR 89!",
                "tags": ["platter"], "keywords": ["family"],
            }), finish_reason="stop")

    async def _models(db):
        return [(SimpleNamespace(id="custom:model"), None)]

    monkeypatch.setattr("app.modules.rag.service.search", _fake_search)
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: _Provider(),
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda mid: ("api-x", "groq"))
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models", _models)
    await _svc.draft_post_content(db, user_id, "Family deal", "offer", None)
    assert "Family platter SAR 89" in seen["msg"]


@pytest.mark.asyncio
async def test_review_reply_context_has_identity_without_databank(
        db, user_id, config_id):
    from sqlalchemy import select as _select

    from app.modules.channels.models import AutoReplyConfig
    from app.modules.channels.review_reply import _build_context

    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma, mixed grill",
                     business_doesnt_sell="shampoo")
    config = (await db.execute(
        _select(AutoReplyConfig).where(AutoReplyConfig.id == config_id)
    )).scalar_one()
    assert not config.databank_id
    text = await _build_context(config, "do you sell shawarma?", db)
    assert "Food & Restaurant" in text
    assert "shawarma" in text
    assert "Does NOT sell" in text


@pytest.mark.asyncio
async def test_profile_patch_roundtrip(client, db, user_id):
    await _make_user(db, user_id)
    r = client.patch("/api/v1/profile", json={
        "business_type": "Food & Restaurant",
        "business_sells": "shawarma, mixed grill",
        "business_doesnt_sell": "shampoo",
        "business_description": "Charcoal grill spot",
    }, headers={"host": "localhost"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["business_type"] == "Food & Restaurant"
    assert body["business_sells"] == "shawarma, mixed grill"
    assert body["business_doesnt_sell"] == "shampoo"
    assert body["business_description"] == "Charcoal grill spot"


async def _make_service(db, channel_id, name, category="Custom", offered=True):
    from app.modules.channels.models import BusinessService

    db.add(BusinessService(channel_id=channel_id, name=name,
                           category=category, is_offered=offered))
    await db.commit()


@pytest.mark.asyncio
async def test_offered_services_scoping(db, user_id, channel_id):
    from app.modules.profile.service import get_offered_services

    await _make_service(db, channel_id, "Charcoal Grill", "Dine-in", True)
    await _make_service(db, channel_id, "Catering", "Custom", True)
    await _make_service(db, channel_id, "Valet Parking", "Custom", False)
    # Channel-scoped: only this channel's offered rows.
    scoped = await get_offered_services(user_id, db, channel_id=channel_id)
    assert "Charcoal Grill (Dine-in)" in scoped
    assert "Catering" in scoped
    assert not any("Valet" in s for s in scoped)
    # Tenant-wide: same rows (single channel tenant).
    wide = await get_offered_services(user_id, db)
    assert scoped == wide
    # Unknown user / no user never raises, returns [].
    assert await get_offered_services("no-such-user", db) == []
    assert await get_offered_services(None, db) == []


def test_identity_includes_services_line():
    text = format_business_identity({"business_type": "Food & Restaurant"},
                                    services=["Charcoal Grill (Dine-in)"])
    assert "Services offered" in text
    assert "Charcoal Grill" in text


@pytest.mark.asyncio
async def test_review_reply_context_includes_service(db, user_id, config_id, channel_id):
    from sqlalchemy import select as _select

    from app.modules.channels.models import AutoReplyConfig
    from app.modules.channels.review_reply import _build_context

    await _make_user(db, user_id, business_type="Food & Restaurant")
    await _make_service(db, channel_id, "Charcoal Grill", "Dine-in", True)
    config = (await db.execute(
        _select(AutoReplyConfig).where(AutoReplyConfig.id == config_id)
    )).scalar_one()
    text = await _build_context(config, "do you have grilled food?", db)
    assert "Services offered" in text
    assert "Charcoal Grill" in text


@pytest.mark.asyncio
async def test_post_draft_prompt_includes_service(monkeypatch, db, user_id, channel_id):
    import json as _json
    from types import SimpleNamespace

    from app.modules.posts import service as _svc

    await _make_user(db, user_id, business_type="Food & Restaurant")
    await _make_service(db, channel_id, "Family Platter", "Dine-in", True)
    await _make_service(db, channel_id, "Closed Service", "Custom", False)
    seen = {}

    class _Provider:
        async def complete(self, req):
            seen["msg"] = req.messages[0].content
            return SimpleNamespace(content=_json.dumps({
                "description": "Family platter night!",
                "tags": ["platter"], "keywords": ["family"],
            }), finish_reason="stop")

    async def _models(db):
        return [(SimpleNamespace(id="custom:model"), None)]

    monkeypatch.setattr(
        "app.modules.llm.providers.registry.get_provider_for_model",
        lambda mid: _Provider(),
    )
    monkeypatch.setattr(
        "app.modules.llm.service._resolve_model", lambda mid: ("api-x", "groq"))
    monkeypatch.setattr(
        "app.modules.llm.providers.registry.list_tenant_models", _models)
    await _svc.draft_post_content(db, user_id, "Weekend deal", "offer", None)
    assert "Family Platter" in seen["msg"]
    assert "Closed Service" not in seen["msg"]


@pytest.mark.asyncio
async def test_failed_probe_does_not_expire_caller_session(db, user_id, channel_id):
    """Missing-table probe (e.g. unmigrated prod DB) must not poison the sync.

    Regression test for "Localith sync failed: greenlet_spawn has not been
    called": the old code rolled back the CALLER's session on probe failure,
    expiring every ORM object — the next attribute access raised
    MissingGreenlet. Savepoint isolation keeps caller state intact.
    """
    from sqlalchemy import select as _select
    from sqlalchemy import text as _text

    from app.modules.review_engine.relevance import resolve_business_domain
    from app.modules.users.models import User

    await _make_user(db, user_id, business_type="Food & Restaurant",
                     business_sells="shawarma grill restaurant food menu")
    user = (await db.execute(
        _select(User).where(User.id == user_id))).scalar_one()
    # Simulate an unmigrated DB: databanks table gone (kept uncommitted so
    # the fixture session rolls it back on teardown).
    await db.execute(_text("DROP TABLE databanks"))
    domain = await resolve_business_domain(channel_id, user_id, db)
    # Other sources still resolve…
    assert "shawarma" in domain["terms"]
    assert "business_context" in domain["sources"]
    assert domain["sources"].get("databanks", 0) == 0
    # …and the caller's ORM objects are untouched — this attribute access
    # raised MissingGreenlet before the fix.
    assert user.business_type == "Food & Restaurant"
    # …and the session still runs fresh queries.
    again = (await db.execute(
        _select(User).where(User.id == user_id))).scalar_one()
    assert again.business_type == "Food & Restaurant"
    await db.rollback()


@pytest.mark.asyncio
async def test_context_probe_failure_returns_fallback_usable_session(db, user_id):
    """get_business_context degrades to {} and leaves the session working."""
    from sqlalchemy import select as _select
    from sqlalchemy import text as _text

    await _make_user(db, user_id, business_type="Food & Restaurant")
    # Break the users-table probe (uncommitted; rolled back at teardown).
    await db.execute(_text("DROP TABLE channel_services"))
    services = await get_offered_services(user_id, db)
    assert services == []
    from app.modules.users.models import User

    user = (await db.execute(
        _select(User).where(User.id == user_id))).scalar_one()
    assert user.business_type == "Food & Restaurant"
    await db.rollback()


@pytest.mark.asyncio
async def test_notify_failure_does_not_poison_session(db, user_id):
    """A failed notify insert must not expire caller state nor retry forever."""
    from sqlalchemy import select as _select
    from sqlalchemy import text as _text

    from app.modules.notifications.service import notify
    from app.modules.users.models import User

    await _make_user(db, user_id, business_type="Food & Restaurant")
    user = (await db.execute(
        _select(User).where(User.id == user_id))).scalar_one()
    await db.execute(_text("DROP TABLE notifications"))
    nid = await notify(db, user_id, "sync_failed", "Sync failed")
    assert nid is None
    # Caller objects untouched (MissingGreenlet before the fix)…
    assert user.business_type == "Food & Restaurant"
    # …and later work isn't haunted by the failed row (no autoflush retry).
    again = (await db.execute(
        _select(User).where(User.id == user_id))).scalar_one()
    assert again.business_type == "Food & Restaurant"
    await db.rollback()
