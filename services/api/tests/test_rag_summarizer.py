"""Phase C: LLM summary enrichment.

Covers strict-JSON parsing, the never-fail guarantee, idempotency (no
re-billing), and the disabled/no-model skip paths. The LLM gateway is
monkeypatched — no network.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.modules.rag import summarizer
from app.modules.rag.models import Document
from app.modules.rag.summarizer import parse_enrichment

# Dedicated in-memory engine (same pattern as the worker tests): enrich_document
# opens its own sessions, so it gets its own engine to guarantee seed + enrich
# + verification all see the same database.
SUM_ENRICH_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
SUM_SESSION = async_sessionmaker(SUM_ENRICH_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _sum_db(monkeypatch):
    async with SUM_ENRICH_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(summarizer, "async_session", SUM_SESSION)
    yield
    # StaticPool engine is shared across tests: clear seeded rows between
    # them so fixed bank/doc ids never collide.
    from sqlalchemy import text

    async with SUM_SESSION() as db:
        await db.execute(text("DELETE FROM documents"))
        await db.execute(text("DELETE FROM databanks"))
        await db.commit()

# ── parse_enrichment ─────────────────────────────────────────────

_VALID = '{"summary": "Pricing plans for teams of all sizes with Arabic support.", "key_points": ["$9/mo", "Arabic dialects", "14-day trial"]}'


def test_parse_accepts_strict_json():
    out = parse_enrichment(_VALID)
    assert out is not None
    assert out["summary"].startswith("Pricing plans")
    assert len(out["key_points"]) == 3


def test_parse_accepts_fenced_json():
    out = parse_enrichment(f"```json\n{_VALID}\n```")
    assert out is not None
    assert out["key_points"]


def test_parse_tolerates_prose_around_json():
    out = parse_enrichment(f"Here you go:\n{_VALID}\nHope this helps!")
    assert out is not None


def test_parse_rejects_garbage_and_thin_summaries():
    assert parse_enrichment("no json at all") is None
    assert parse_enrichment('{"summary": "short", "key_points": []}') is None
    assert parse_enrichment('{"key_points": ["a"]}') is None
    assert parse_enrichment('{"summary": 42}') is None
    assert parse_enrichment("") is None


def test_parse_caps_key_points():
    many = ", ".join(f'"p{i}"' for i in range(12))
    out = parse_enrichment(f'{{"summary": "A sufficiently long factual summary.", "key_points": [{many}]}}')
    assert out is not None
    assert len(out["key_points"]) == 6


# ── enrich_document ──────────────────────────────────────────────

@pytest.fixture
def enrich_env(monkeypatch):
    """Common seams: storage stub + settings on (DB handled by _sum_db)."""
    monkeypatch.setattr("app.core.storage.get_doc", lambda bank, key: b"# Pricing\nPlans start at $9 per month.\n## Enterprise\nContact sales.")
    monkeypatch.setattr("app.modules.rag.summarizer.settings.RAG_AI_SUMMARY_ENABLED", True)


async def _seed_doc(db=None, *, meta=None) -> str:
    from app.modules.rag.models import Databank

    async with SUM_SESSION() as db:
        bank = "enrich-bank-0001"
        db.add(Databank(id=bank, user_id="enrich-user-0001", name="Enrich"))
        doc = Document(
            id="enrich-doc-0001", databank_id=bank, user_id="enrich-user-0001",
            filename="https://example.com/en/pricing", source_type="scrape",
            source_url="https://example.com/en/pricing", file_type="md",
            status="completed", lang="en", variant_group="/pricing",
            meta=meta or {"summary": "extractive", "intent": "pricing"},
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def _get_doc(doc_id: str, db=None) -> Document:
    async with SUM_SESSION() as db:
        return (await db.execute(select(Document).where(Document.id == doc_id))).scalars().one()


@pytest.mark.asyncio
async def test_enrich_updates_meta(enrich_env, monkeypatch):
    doc_id = await _seed_doc()

    class _Resp:
        content = _VALID

    async def _fake_complete(**kwargs):
        assert kwargs["purpose"] == summarizer.SUMMARY_PURPOSE
        assert kwargs["tenant_id"] == "enrich-user-0001"
        return _Resp()

    async def _fake_model(db_):
        return "openai:gpt-4o-mini"

    monkeypatch.setattr("app.modules.llm.gateway.complete", _fake_complete)
    monkeypatch.setattr("app.modules.llm.gateway.resolve_tenant_model", _fake_model)

    assert await summarizer.enrich_document(doc_id) is True

    doc = await _get_doc(doc_id)
    assert doc.meta["ai_summary"].startswith("Pricing plans")
    assert doc.meta["ai_key_points"] == ["$9/mo", "Arabic dialects", "14-day trial"]
    assert doc.meta["enriched_at"]


@pytest.mark.asyncio
async def test_enrich_is_idempotent(enrich_env, monkeypatch):
    doc_id = await _seed_doc(meta={"summary": "s", "enriched_at": datetime.now(timezone.utc).isoformat()})

    calls = []

    async def _fail_complete(**kwargs):
        calls.append(1)
        raise AssertionError("must not call the LLM for an enriched doc")

    monkeypatch.setattr("app.modules.llm.gateway.complete", _fail_complete)
    assert await summarizer.enrich_document(doc_id) is False
    assert calls == []


@pytest.mark.asyncio
async def test_enrich_never_raises_on_provider_failure(enrich_env, monkeypatch):
    doc_id = await _seed_doc()

    async def _boom(**kwargs):
        raise RuntimeError("provider down")

    async def _fake_model(db_):
        return "openai:gpt-4o-mini"

    monkeypatch.setattr("app.modules.llm.gateway.complete", _boom)
    monkeypatch.setattr("app.modules.llm.gateway.resolve_tenant_model", _fake_model)

    assert await summarizer.enrich_document(doc_id) is False
    doc = await _get_doc(doc_id)
    assert doc.meta.get("ai_summary") is None  # extractive fallback intact


@pytest.mark.asyncio
async def test_enrich_skips_without_model(enrich_env, monkeypatch):
    doc_id = await _seed_doc()

    async def _no_model(db_):
        return None

    monkeypatch.setattr("app.modules.llm.gateway.resolve_tenant_model", _no_model)
    assert await summarizer.enrich_document(doc_id) is False


@pytest.mark.asyncio
async def test_enrich_discards_unusable_answer(enrich_env, monkeypatch):
    doc_id = await _seed_doc()

    class _Resp:
        content = "The page is about pricing, honestly."

    async def _fake_complete(**kwargs):
        return _Resp()

    async def _fake_model(db_):
        return "openai:gpt-4o-mini"

    monkeypatch.setattr("app.modules.llm.gateway.complete", _fake_complete)
    monkeypatch.setattr("app.modules.llm.gateway.resolve_tenant_model", _fake_model)

    assert await summarizer.enrich_document(doc_id) is False
    doc = await _get_doc(doc_id)
    assert doc.meta.get("ai_summary") is None
