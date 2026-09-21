"""Retrieval Layer: the single doorway to tenant business information.

Callers declare WHAT they need (EvidenceNeed: product / offer /
business_profile / business_overview). The layer decides HOW: it queries
the applicable mechanisms (structured, hybrid, external when opted in),
merges by score, minimizes to the need's budget, and renders facts-only
context. The LLM never learns which mechanism produced a fact.

Tenant isolation: every snapshot probe is scoped to the tenant's databank
ids (explicit > channel-linked > all tenant's). External sources are
scoped the same way; credentials never leave the server.
"""
import asyncio
import logging

from . import mechanisms
from .evidence import (
    LIVE_CAPABLE_NEEDS,
    NEED_BUDGETS,
    NEED_BUSINESS_OVERVIEW,
    NEED_BUSINESS_PROFILE,
    NEED_OFFER,
    NEED_PRODUCT,
    Evidence,
    EvidenceNeed,
    EvidenceResult,
)

logger = logging.getLogger(__name__)

# record_type values the structured store understands per need.
# Empty list = all record types (menus, hours, policies and offers are all
# legitimate business-profile/overview facts).
_STRUCTURED_TYPES = {
    NEED_PRODUCT: ["product"],
    NEED_OFFER: ["offer", "pricing_rule"],
    NEED_BUSINESS_PROFILE: [],
    NEED_BUSINESS_OVERVIEW: [],
}


def _overlap_score(query: str, fact: str) -> float:
    from .mechanisms import _terms

    q = set(_terms(query, min_len=3))
    if not q:
        return 0.0
    f = set(_terms(fact, min_len=3))
    return len(q & f) / len(q)


def _minimize(need: EvidenceNeed, items: list[Evidence]) -> list[Evidence]:
    """De-duplicate and cut to the need's budget, ranked by mechanism
    score blended with query-term overlap (stable, deterministic)."""
    seen: dict[str, Evidence] = {}
    for e in items:
        key = " ".join(sorted(set((e.fact or "").lower().split())))[:200]
        prev = seen.get(key)
        score = e.score + 0.5 * _overlap_score(need.query, e.fact)
        if prev is None or score > prev.score:
            seen[key] = Evidence(kind=e.kind, fact=e.fact, score=score,
                                 mechanism=e.mechanism, origin=e.origin)
    budget = need.limit or NEED_BUDGETS.get(need.kind, 3)
    ranked = sorted(seen.values(), key=lambda e: e.score, reverse=True)
    return ranked[: max(budget, 1)]


async def retrieve_evidence(
    needs: list[EvidenceNeed],
    *,
    tenant_id: str | None,
    channel_id: str | None = None,
    db,
    bank_id: str | None = None,
    allow_live: bool = False,
) -> dict[str, EvidenceResult]:
    """Fulfill evidence needs from the tenant's Data Bank sources.

    Snapshot mechanisms (structured + hybrid) always run where applicable;
    the external mechanism runs only when `allow_live` is set and the need
    supports it. Never raises — an unfulfilled need yields an empty result
    so the strategy layer can prune instead of failing the pipeline.
    """
    out: dict[str, EvidenceResult] = {}
    if not needs or not tenant_id:
        return {n.kind: EvidenceResult(need=n) for n in (needs or [])}
    try:
        bank_ids = await mechanisms.resolve_bank_ids(
            db, tenant_id, channel_id, bank_id
        )
    except Exception as e:
        logger.debug("Bank resolution failed: %s", e)
        bank_ids = []
    for need in needs:
        try:
            out[need.kind] = await _fulfill_one(
                need, tenant_id, channel_id, db, bank_ids, allow_live
            )
        except Exception as e:
            logger.debug("Evidence %s failed: %s", need.kind, e)
            out[need.kind] = EvidenceResult(need=need)
    return out


async def _fulfill_one(need: EvidenceNeed, tenant_id: str,
                       channel_id: str | None, db, bank_ids: list[str],
                       allow_live: bool) -> EvidenceResult:
    coros = []
    if need.kind in _STRUCTURED_TYPES:
        coros.append(mechanisms.structured_lookup(
            db, tenant_id, bank_ids, _STRUCTURED_TYPES[need.kind],
            need.query, limit=(need.limit or NEED_BUDGETS[need.kind]) * 2,
        ))
    if need.kind in (NEED_PRODUCT, NEED_OFFER, NEED_BUSINESS_PROFILE,
                     NEED_BUSINESS_OVERVIEW):
        coros.append(mechanisms.hybrid_lookup(
            db, bank_ids, need.query,
            top_k=(need.limit or NEED_BUDGETS[need.kind]) * 2,
        ))
    use_live = (
        allow_live and need.kind in LIVE_CAPABLE_NEEDS and bool(bank_ids)
    )
    if use_live:
        coros.append(mechanisms.external_lookup(
            db, tenant_id, bank_ids, need.query,
            limit=(need.limit or NEED_BUDGETS[need.kind]),
        ))
    if not coros:
        return EvidenceResult(need=need)

    names = (
        (["structured"] if need.kind in _STRUCTURED_TYPES else [])
        + ["hybrid"]
        + (["external"] if use_live else [])
    )
    raw = await asyncio.gather(*coros, return_exceptions=True)
    items: list[Evidence] = []
    for name, res in zip(names, raw):
        if isinstance(res, Exception):
            logger.debug("Mechanism %s failed for %s: %s", name, need.kind, res)
            continue
        for fact, score in res or []:
            if (fact or "").strip():
                items.append(Evidence(kind=need.kind, fact=fact.strip()[:800],
                                      score=float(score or 0), mechanism=name))
    for e in _minimize(need, items):
        logger.debug("Evidence %s via %s (%.3f): %.80s",
                     e.kind, e.mechanism, e.score, e.fact)
    return EvidenceResult(need=need, items=_minimize(need, items))


async def identity(db, tenant_id: str | None,
                   channel_id: str | None = None) -> str:
    """Owner-configured identity facts, rendered for prompts."""
    return await mechanisms.identity_block(db, tenant_id, channel_id)


async def domain_vocabulary(db, tenant_id: str,
                            channel_id: str | None = None) -> dict:
    """Business-domain vocabulary for relevance assessment."""
    return await mechanisms.domain_vocabulary(db, tenant_id, channel_id)
