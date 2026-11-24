"""The shared knowledge layer: every brain gets the same sources, per-surface."""
import pytest

from app.modules.assistant.reply_context import (
    CATALOG,
    FACTS,
    GROUNDING,
    IDENTITY,
    MEMORY,
    SURFACE_SOURCES,
    build_reply_context,
)

pytestmark = pytest.mark.asyncio


def _patch_sources(monkeypatch, markers=None, raisers=()):
    """Point every source at a marker string (or an exception)."""
    from app.modules.catalog import service as catalog_service
    from app.modules.memory import service as memory_service
    from app.modules.profile import business_profile, facts_store
    from app.modules.profile import facts_tool
    from app.modules.rag import grounding

    markers = markers or {}

    async def _id(tenant_id, db):
        if IDENTITY in raisers:
            raise RuntimeError("identity down")
        return markers.get(IDENTITY, "IDENTITY-MARK")

    async def _facts(db, tenant_id, **kw):
        if FACTS in raisers:
            raise RuntimeError("facts down")
        return {"business": {"name": markers.get(FACTS, "FACTS-MARK")}}

    async def _ground(db, tenant_id=None, channel_id=None, query=None):
        if GROUNDING in raisers:
            raise RuntimeError("grounding down")
        return markers.get(GROUNDING, "GROUNDING-MARK")

    async def _catalog(db, tenant_id=None, query=None, allow_image=False):
        if CATALOG in raisers:
            raise RuntimeError("catalog down")
        return markers.get(CATALOG, "CATALOG-MARK")

    async def _memory(db, tenant_id=None, query=None, enabled=True):
        if MEMORY in raisers:
            raise RuntimeError("memory down")
        return markers.get(MEMORY, "MEMORY-MARK")

    monkeypatch.setattr(business_profile, "prompt_block", _id)
    monkeypatch.setattr(facts_store, "get_facts", _facts)
    monkeypatch.setattr(grounding, "reply_block", _ground)
    monkeypatch.setattr(catalog_service, "catalog_block", _catalog)
    monkeypatch.setattr(memory_service, "reply_block", _memory)
    monkeypatch.setattr(facts_tool, "detect_topics", lambda text: [])
    monkeypatch.setattr(facts_tool, "render_topic", lambda facts, topic: "")


async def test_whatsapp_surface_gets_every_source(db, monkeypatch):
    _patch_sources(monkeypatch)
    ctx = await build_reply_context(
        db, tenant_id="t1", surface="whatsapp", query="hi", channel_id="c1"
    )
    rendered = ctx.render()
    for marker in ("IDENTITY-MARK", "FACTS-MARK", "GROUNDING-MARK", "CATALOG-MARK", "MEMORY-MARK"):
        assert marker in rendered
    assert set(ctx.sizes) == set(SURFACE_SOURCES["whatsapp"])


async def test_reviews_surface_excludes_catalog_and_memory(db, monkeypatch):
    """Public Google replies must not carry prices or private chat memory."""
    _patch_sources(monkeypatch)
    ctx = await build_reply_context(db, tenant_id="t1", surface="reviews", query="hi")
    rendered = ctx.render()
    assert "FACTS-MARK" in rendered
    assert "CATALOG-MARK" not in rendered
    assert "MEMORY-MARK" not in rendered
    assert "IDENTITY-MARK" not in rendered  # channel-scoped identity stays in the engine
    assert "GROUNDING-MARK" not in rendered  # the engine retrieves by strategy need


async def test_dashboard_surface_gains_facts_and_catalog(db, monkeypatch):
    _patch_sources(monkeypatch)
    ctx = await build_reply_context(db, tenant_id="t1", surface="dashboard", query="hours?")
    rendered = ctx.render()
    assert "FACTS-MARK" in rendered
    assert "CATALOG-MARK" in rendered


async def test_a_dead_source_never_costs_the_reply(db, monkeypatch):
    _patch_sources(monkeypatch, raisers=(GROUNDING, CATALOG))
    ctx = await build_reply_context(
        db, tenant_id="t1", surface="whatsapp", query="hi", channel_id="c1"
    )
    rendered = ctx.render()
    assert "IDENTITY-MARK" in rendered
    assert "FACTS-MARK" in rendered
    assert "MEMORY-MARK" in rendered
    assert GROUNDING not in ctx.sizes
    assert CATALOG not in ctx.sizes


async def test_facts_tool_framing_for_the_whatsapp_surface(db, monkeypatch):
    from app.modules.profile import facts_tool

    _patch_sources(monkeypatch)
    monkeypatch.setattr(facts_tool, "detect_topics", lambda text: ["locations"])
    monkeypatch.setattr(facts_tool, "render_topic", lambda facts, topic: "LOC-SLICE")
    ctx = await build_reply_context(
        db, tenant_id="t1", surface="whatsapp", query="where are you?",
        facts_tool_framing=True,
    )
    assert 'get_business_facts(topic="locations")' in ctx.render()
    assert "LOC-SLICE" in ctx.render()
