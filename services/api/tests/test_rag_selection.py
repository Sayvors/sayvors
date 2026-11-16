"""Assistant databank selection: pick the bank that actually holds context.

Regression: the assistant used to search an arbitrary first bank (often empty)
while another tenant bank had hundreds of searchable chunks.
"""
import pytest

from app.modules.rag.models import Databank, Document, DocumentChunk
from app.modules.rag.selection import select_databank_for_question

_TENANT = "select-user-0001"
_OTHER = "select-user-0002"


async def _seed(db, bank_id: str, name: str, chunks: list[str], *, user_id=_TENANT, status="completed"):
    db.add(Databank(id=bank_id, user_id=user_id, name=name))
    if not chunks:
        return
    doc_id = f"doc-{bank_id}"
    db.add(Document(
        id=doc_id, databank_id=bank_id, user_id=user_id,
        filename=f"{name}.md", source_type="scrape", file_type="md", status=status,
    ))
    for i, text in enumerate(chunks):
        db.add(DocumentChunk(
            id=f"chunk-{bank_id}-{i}", document_id=doc_id, databank_id=bank_id,
            content=text, seq=i,
        ))


@pytest.mark.asyncio
async def test_selects_bank_matching_the_question(db):
    # Empty bank created first — the old limit(1) would have picked this one.
    await _seed(db, "sel-empty", "Empty bank", [])
    await _seed(db, "sel-content", " dialects bank", [
        "Arabic dialects matter for customer service in Gulf and Egypt.",
        "Reply in the same dialect the customer used.",
    ])
    await _seed(db, "sel-big", "Big bank", [f"Unrelated paragraph number {i} about shipping." for i in range(8)])
    await _seed(db, "sel-other-tenant", "Other tenant", ["Arabic dialects private"], user_id=_OTHER)
    await db.commit()

    bank_id, name = await select_databank_for_question(
        db, _TENANT, "Arabic dialects agent"
    )
    assert bank_id == "sel-content"
    assert name == " dialects bank"


@pytest.mark.asyncio
async def test_falls_back_to_most_indexed_bank_without_keyword_hit(db):
    await _seed(db, "sel-empty2", "Empty", [])
    await _seed(db, "sel-small", "Small", ["A short note about cats."])
    await _seed(db, "sel-large", "Large", [f"Generic record {i}." for i in range(7)])
    await db.commit()

    bank_id, _ = await select_databank_for_question(
        db, _TENANT, "zzzqqq neverappears"
    )
    assert bank_id == "sel-large"


@pytest.mark.asyncio
async def test_other_tenant_bank_never_selected_even_with_better_match(db):
    """A foreign bank with MORE chunks and an exact match must stay invisible."""
    await _seed(db, "sel-own", "Own", ["A short note about shipping."])
    await _seed(db, "sel-foreign", "Foreign", [
        "Arabic dialects private customer data.",
        *[f"Foreign tenant secret record {i} about Arabic dialects." for i in range(20)],
    ], user_id=_OTHER)
    await db.commit()

    for question in (
        "Arabic dialects private customer data",
        "secret foreign tenant record",
        "shipping",
        "",  # fallback path must stay isolated too
    ):
        bank_id, _ = await select_databank_for_question(db, _TENANT, question)
        assert bank_id == "sel-own", f"leaked foreign bank for {question!r}"


@pytest.mark.asyncio
async def test_no_banks_returns_none(db):
    # Another tenant has plenty of data; that must not count as ours.
    await _seed(db, "sel-only-other", "Other tenant", ["Arabic dialects secret"], user_id=_OTHER)
    await db.commit()

    bank_id, name = await select_databank_for_question(
        db, "select-user-empty-0003", "anything"
    )
    assert (bank_id, name) == (None, None)
