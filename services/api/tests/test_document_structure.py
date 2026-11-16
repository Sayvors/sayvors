"""Phase B: structured extraction + heading-aware chunking.

Deterministic (no network, no LLM): summary/intent/sections/entities from
`document_structure`, heading-trail chunk metadata from `chunker`.
"""
import re

import pytest

from app.modules.rag.chunker import chunk_markdown, chunk_text
from app.modules.rag.document_structure import (
    build_structured_doc,
    classify_intent,
    extract_entities,
    extract_sections,
    extract_summary,
)

_MD = """# Sayvors Pricing
Simple, transparent pricing for every team.
## Annual plan
Costs $99 per month, billed yearly. Contact sales@example.com or call +20 100 123 4567.
Includes unlimited channels and Arabic dialect support.
## Free trial
Try it 14 days, no card required.
"""


def test_classify_intent_from_url_and_title():
    assert classify_intent("https://s.com/pricing", None) == "pricing"
    assert classify_intent("https://s.com/en/blog/post-1", None) == "blog"
    assert classify_intent("https://s.com/privacy", None) == "policy"
    assert classify_intent("https://s.com/x", "Contact our team") == "contact"
    assert classify_intent("https://s.com/x", "Anything") == "general"


def test_extract_summary_first_paragraph_cut_at_sentence():
    summary = extract_summary(_MD)
    assert summary.startswith("Simple, transparent pricing")
    assert "$99" in summary
    assert len(summary) <= 320


def test_extract_sections_outline_with_sizes():
    sections = extract_sections(_MD)
    headings = [s["heading"] for s in sections]
    assert "Sayvors Pricing" in headings
    assert "Annual plan" in headings
    assert "Free trial" in headings
    annual = next(s for s in sections if s["heading"] == "Annual plan")
    assert annual["level"] == 2
    assert annual["chars"] > 0


def test_extract_entities_bounded_and_plausible():
    entities = extract_entities(_MD)
    assert "sales@example.com" in entities["emails"]
    assert any("99" in p for p in entities["prices"])
    # False-positive guard: date-like/short digit runs are not phones.
    assert all(7 <= len(re.sub(r"\D", "", ph)) <= 15 for ph in entities["phones"])


def test_build_structured_doc_shape():
    meta = build_structured_doc(
        "https://s.com/en/pricing", "Pricing", _MD, "en"
    )
    assert meta["intent"] == "pricing"
    assert meta["lang"] == "en"
    assert meta["title"] == "Pricing"
    assert meta["word_count"] > 10
    assert meta["summary"]
    assert len(meta["sections"]) == 3


def test_chunk_markdown_keeps_sections_and_trail():
    chunks = chunk_markdown(_MD, max_tokens=60, overlap_tokens=10)
    assert len(chunks) >= 3
    # No chunk mixes sections: "Annual plan" content stays within its chunks.
    annual_chunks = [c for c in chunks if c["metadata"]["section"] == "Sayvors Pricing › Annual plan"]
    assert annual_chunks
    assert all("$99" in c["content"] or "sales@example.com" in c["content"] or "Arabic" in c["content"] for c in annual_chunks)
    assert all("no card required" not in c["content"] for c in annual_chunks)
    # Index present on every chunk.
    assert all(isinstance(c["metadata"]["index"], int) for c in chunks)


def test_chunk_text_plain_text_has_no_section():
    chunks = chunk_text("One sentence. Two sentences. Three sentences. Four!", max_tokens=10, overlap_tokens=2)
    assert chunks
    assert chunks[0]["metadata"]["section"] is None
    assert all("metadata" in c for c in chunks)  # consumers rely on the key


def test_chunk_text_uploads_get_base_metadata():
    base = {"lang": "ar", "source_url": "https://s.com/ar/about"}
    chunks = chunk_text("# About\nعن الشركة. نص تجريبي للفحص.", metadata=base)
    assert chunks
    assert all(c["metadata"]["lang"] == "ar" for c in chunks)
    assert all(c["metadata"]["source_url"] == "https://s.com/ar/about" for c in chunks)


# ── Upsert stores structured meta (Phase B wiring) ──────────────

@pytest.mark.asyncio
async def test_upsert_scrape_document_stores_meta(db, monkeypatch):
    from sqlalchemy import select

    from app.modules.rag.jobs import _upsert_scrape_document
    from app.modules.rag.models import Databank, Document

    monkeypatch.setattr("app.core.storage.put_doc", lambda *a, **k: None)
    bank_id = "phase-b-meta-bank"
    db.add(Databank(id=bank_id, user_id="crawl-upsert-user", name="Phase B"))
    await db.commit()
    url = "https://example.com/en/pricing"
    markdown = "# Pricing\nPlans start at $9 per month.\n## Enterprise\nTalk to sales@example.com."

    doc_id = await _upsert_scrape_document(
        db, bank_id, "crawl-upsert-user", url, markdown,
        lang="en", variant_group="/pricing", title="Pricing",
    )
    assert doc_id

    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalars().one()
    assert doc.meta is not None
    assert doc.meta["intent"] == "pricing"
    assert doc.meta["lang"] == "en"
    assert "Plans start at $9" in doc.meta["summary"]
    assert any(s["heading"] == "Enterprise" for s in doc.meta["sections"])
