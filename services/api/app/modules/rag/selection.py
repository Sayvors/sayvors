"""Databank selection for assistant-wide RAG.

The assistant used to take ``select(Databank.id) … limit(1)`` — an arbitrary
bank, often empty, so questions answered "no evidence" while another bank had
hundreds of indexed chunks. Selection now prefers:

1. a bank whose chunks actually match the question (cheap keyword probe via
   the shared retrieval path — no LLM call), then
2. the bank with the most indexed content (chunks, then completed docs),
   with a bounded scan and deterministic tie-break.

The chosen bank is still passed to the normal agent, so all tenant isolation,
tool scoping and citations stay unchanged.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Databank, Document, DocumentChunk

# Bound the fan-out: a tenant with hundreds of banks must not turn one chat
# message into hundreds of retrieval probes.
MAX_CANDIDATE_BANKS = 20
PROBE_TOP_K = 3


async def select_databank_for_question(
    db: AsyncSession, tenant_id: str, question: str | None = None
) -> tuple[str | None, str | None]:
    """Return ``(databank_id, databank_name)`` best suited to the question."""
    banks = (
        await db.execute(
            select(Databank)
            .where(Databank.user_id == tenant_id)
            .order_by(Databank.created_at.desc())
            .limit(MAX_CANDIDATE_BANKS)
        )
    ).scalars().all()
    if not banks:
        return None, None

    ids = [bank.id for bank in banks]
    chunk_counts = dict(
        (
            await db.execute(
                select(DocumentChunk.databank_id, func.count())
                .where(DocumentChunk.databank_id.in_(ids))
                .group_by(DocumentChunk.databank_id)
            )
        ).all()
    )
    doc_counts = dict(
        (
            await db.execute(
                select(Document.databank_id, func.count())
                .where(
                    Document.databank_id.in_(ids),
                    Document.status == "completed",
                )
                .group_by(Document.databank_id)
            )
        ).all()
    )

    by_id = {bank.id: bank for bank in banks}
    indexed = [bid for bid in ids if chunk_counts.get(bid, 0) > 0]

    # 1. Question-aware probe: which indexed bank has real matching chunks?
    if question and question.strip() and indexed:
        from .search import hybrid_search

        best_id: str | None = None
        best_score = 0.0
        for bank_id in indexed:
            try:
                hits = await hybrid_search(
                    databank_id=bank_id,
                    query_vector=None,  # keyword probe only — no embedding cost
                    query_text=question,
                    top_k=PROBE_TOP_K,
                    db=db,
                )
            except Exception:  # noqa: BLE001 — one bad bank must not block chat
                continue
            if not hits:
                continue
            # More matching chunks + stronger top rank wins; tiny epsilon keeps
            # ordering stable when several banks have identical hit counts.
            score = len(hits) + float(hits[0].get("score") or 0.0)
            if score > best_score:
                best_score, best_id = score, bank_id
        if best_id:
            bank = by_id[best_id]
            return bank.id, bank.name

    # 2. No keyword evidence: prefer the bank with the most indexed content.
    # If nothing is indexed yet, fall back to the bank with the most completed
    # documents (it may be mid-ingest); empty banks never win over either.
    ranked = sorted(
        ids,
        key=lambda bid: (chunk_counts.get(bid, 0), doc_counts.get(bid, 0)),
        reverse=True,
    )
    chosen = next((bid for bid in ranked if chunk_counts.get(bid, 0) or doc_counts.get(bid, 0)), ranked[0])
    bank = by_id[chosen]
    return bank.id, bank.name
